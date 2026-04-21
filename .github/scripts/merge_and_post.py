import argparse
import glob
import os
import re
import sys

import requests
from jinja2 import Environment, FileSystemLoader
from junitparser import Error, Failure, JUnitXml

MARKER    = "<!-- ci-test-summary -->"
SERVER    = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
API       = os.environ.get("GITHUB_API_URL",    "https://api.github.com")
WORKSPACE = os.environ.get("GITHUB_WORKSPACE",  "").rstrip("/")


def extract_gtest_failure(system_out, test_name):
    """Extract assertion lines between [ RUN ] and [ FAILED ] for an exact test name match."""
    capturing, captured_lines = False, []
    for line in (system_out or "").splitlines():
        if f"[ RUN      ] {test_name}" in line:
            capturing = True
            continue
        if capturing:
            if f"[  FAILED  ] {test_name}" in line:
                break
            captured_lines.append(line)
    return "\n".join(captured_lines).strip()


def extract_all_gtest_failures(system_out):
    """Fallback parser for CTest-wrapped GTest logs where testcase names don't match JUnit case names.

    Captures all failed GTest blocks from system_out so messages aren't empty.
    """
    current_test = None
    current_lines = []
    failed_blocks = []

    for line in (system_out or "").splitlines():
        run_match = re.match(r"^\[\s*RUN\s*\]\s+(.+)$", line)
        if run_match:
            current_test = run_match.group(1).strip()
            current_lines = []
            continue

        failed_match = re.match(r"^\[\s*FAILED\s*\]\s+(.+?)(?:\s+\(.*\))?$", line)
        if failed_match:
            failed_test = failed_match.group(1).strip()
            if current_test and failed_test == current_test:
                body = "\n".join([l for l in current_lines if l.strip()]).strip()
                if body:
                    failed_blocks.append(body)
            current_test = None
            current_lines = []
            continue

        if current_test is not None:
            current_lines.append(line)

    return "\n\n".join(failed_blocks).strip()


def build_source_link(failure_text, repo, sha):
    """Parse a file:line header from a GTest failure block and return (display_text, url)."""
    if not failure_text:
        return "", ""

    path, line = "", ""
    for raw in failure_text.strip().splitlines():
        match = re.match(r'^(.+?):(\d+):\s+\w+', raw.strip())
        if match:
            path, line = match.group(1), match.group(2)
            break

    if not path:
        return "", ""

    if WORKSPACE and path.startswith(WORKSPACE):
        path = path[len(WORKSPACE):].lstrip("/")

    url = f"{SERVER}/{repo}/blob/{sha}/{path}#L{line}" if repo else ""
    return f"{path}:{line}", url


def parse_xml_file(xml_path, platform, repo, sha):
    """Parse a CTest JUnit XML file and return (failures, passed_count, total_count)."""
    failures, passed = [], 0
    for suite in JUnitXml.fromfile(xml_path):
        for case in suite:
            if case.result and isinstance(case.result[0], (Failure, Error)):
                body = extract_gtest_failure(case.system_out, case.name)
                if not body:
                    body = extract_all_gtest_failures(case.system_out)
                if not body:
                    body = str(case.result[0]) if case.result else "No failure details found"

                link_text, link_url = build_source_link(body, repo, sha)
                failures.append({
                    "name":      f"{suite.name}.{case.name}",
                    "link_text": link_text,
                    "link_url":  link_url,
                    "message":   body.strip(),
                })
            else:
                passed += 1
    return failures, passed, passed + len(failures)


def load_all_results(xml_dir, repo, sha):
    """Find all XML files under xml_dir and parse them, returning a list of result dicts."""
    xml_files = sorted(glob.glob(os.path.join(xml_dir, "**", "*.xml"), recursive=True))
    if not xml_files:
        print(f"No XML files found in '{xml_dir}' — nothing to report.")
        sys.exit(0)

    results = []
    for xml_path in xml_files:
        parent = os.path.basename(os.path.dirname(xml_path))
        stem   = os.path.splitext(os.path.basename(xml_path))[0]

        if parent.startswith("test-results-") and parent != "test-results":
            platform = parent.replace("test-results-", "", 1)
        else:
            platform = stem.replace("test-results-", "", 1) if stem.startswith("test-results-") else stem

        print(f"Parsing '{xml_path}' (platform: {platform}) ...")
        failures, passed, total = parse_xml_file(xml_path, platform, repo, sha)
        print(f"  -> {passed}/{total} passed, {len(failures)} failed")
        results.append({"platform": platform, "failures": failures, "passed": passed, "total": total})
    return results


def render_comment(results, run_url, sha):
    """Render the markdown comment from the Jinja2 template file."""
    template_dir = os.path.dirname(os.path.abspath(__file__))
    env          = Environment(loader=FileSystemLoader(template_dir), keep_trailing_newline=True)
    template     = env.get_template("comment_template.md.j2")

    for r in results:
        r["platform_link"] = f"[{r['platform']}]({run_url})" if run_url else r["platform"]

    return template.render(marker=MARKER, results=results, run_url=run_url, sha=sha)


def write_step_summary(comment_body):
    """Write the comment body (without the HTML marker) to the GitHub Actions job summary."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(comment_body.replace(MARKER, "").strip() + "\n")


def find_existing_comment(comments_url, headers):
    """Page through PR comments and return the ID of the one containing MARKER, or None."""
    for page in range(1, 10):
        response = requests.get(comments_url, headers=headers, params={"per_page": 100, "page": page})
        response.raise_for_status()
        comments = response.json()
        for comment in comments:
            if MARKER in comment.get("body", ""):
                return comment["id"]
        if len(comments) < 100:
            break
    return None


def post_pr_comment(comment_body, repo, pr_number):
    """Post or update the PR comment using GITHUB_TOKEN."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GH_TOKEN / GITHUB_TOKEN is not set.")
        sys.exit(1)

    headers = {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    comments_url = f"{API}/repos/{repo}/issues/{pr_number}/comments"
    existing_id  = find_existing_comment(comments_url, headers)

    if existing_id:
        print(f"Updating existing comment {existing_id} ...")
        result = requests.patch(f"{API}/repos/{repo}/issues/comments/{existing_id}",
                                headers=headers, json={"body": comment_body})
    else:
        print("Posting new comment ...")
        result = requests.post(comments_url, headers=headers, json={"body": comment_body})

    result.raise_for_status()
    print(f"Done: {result.json().get('html_url', '')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml-dir",   required=True)
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--repo",      default="")
    parser.add_argument("--run-id",    default="")
    parser.add_argument("--sha",       default="HEAD")
    args = parser.parse_args()

    run_url      = f"{SERVER}/{args.repo}/actions/runs/{args.run_id}" if args.repo and args.run_id else ""
    results      = load_all_results(args.xml_dir, args.repo, args.sha)
    comment_body = render_comment(results, run_url, args.sha)

    write_step_summary(comment_body)

    if args.pr_number and args.repo:
        post_pr_comment(comment_body, args.repo, args.pr_number)


if __name__ == "__main__":
    main()
