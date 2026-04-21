# eCAL CI Failure Summary (Reusable Workflow)

Reusable GitHub workflow to summarize CTest/GTest JUnit failures across artifacts and publish:

- GitHub Step Summary
- one marker-based PR comment (updated, not duplicated)

Repository: `YannikSpaeth/ecal-ci-pipeline-improvements`

---

## What this workflow does

1. Downloads JUnit artifacts (default pattern: `test-results-*`)
2. Parses failed tests
3. Renders compact per-platform summary
4. Adds links to:
   - source file + line (when available)
   - `Run Tests` log step line in CI job (best-effort)
5. Writes Step Summary and optionally posts/updates PR comment

---

## How to use

### 1) In your build workflow, export JUnit XML and upload artifact

Example (Ubuntu matrix):

```yaml
- name: Run Tests
  run: |
    mkdir -p "${{ github.workspace }}/_build/test-results"
    ctest -V --test-dir _build --output-junit "${{ github.workspace }}/_build/test-results/test-results-${{ matrix.os }}.xml"

- name: Upload JUnit XML
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: test-results-${{ matrix.os }}
    path: ${{ github.workspace }}/_build/test-results/test-results-${{ matrix.os }}.xml
    if-no-files-found: warn
```

### 2) Add a report job that calls this reusable workflow

```yaml
report-tests:
  needs: [build-ubuntu]
  if: always()
  permissions:
    contents: read
    pull-requests: write
  uses: YannikSpaeth/ecal-ci-pipeline-improvements/.github/workflows/ci-failure-summary.yml@main
  with:
    artifact_name: test-results-*
    pr_number: ${{ github.event.pull_request.number }}
    sha: ${{ github.sha }}
  secrets: inherit
```

> For reproducibility in production, pin to a commit SHA instead of `@main`.

---

## Inputs

Defined by `.github/workflows/ci-failure-summary.yml`:

- `artifact_name` (string, default `test-results-*`)
- `pr_number` (string, optional)
- `sha` (string, optional)

If `pr_number` is empty, summary is still generated in Step Summary, but no PR comment is posted.

---

## Requirements in caller repo

- Build jobs must upload JUnit XML artifacts.
- Artifact names must match the selected `artifact_name` pattern.
- Workflow permissions must allow:
  - `contents: read`
  - `pull-requests: write` (for PR comment updates)

---

## Troubleshooting

### “No XML files found in 'test-results'”
- Check artifact upload path and filename.
- Check artifact naming pattern matches `artifact_name`.
- Ensure upload step has `if: always()`.

### Summary runs but PR comment is missing
- `pr_number` may be empty (common on `push` events).
- Trigger from PR context or pass `pr_number` explicitly.

### Empty or weak failure details
- Ensure your test runner writes useful `system-out` into JUnit.
- Current parser is optimized for CTest + GTest style logs.

---

## Scope note

This workflow focuses on **test-failure summarization** (JUnit/GTest context), not full CMake/build error summarization.
