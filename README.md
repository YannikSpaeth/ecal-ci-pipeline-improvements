# eCAL CI Pipeline Improvements

Minimal reusable CI summary workflow for CTest/JUnit artifacts.

## Included
- `.github/workflows/ci-failure-summary.yml`
- `.github/scripts/merge_and_post.py`
- `.github/scripts/comment_template.md.j2`

## What it does
- downloads JUnit XML artifacts
- parses failed tests and writes a GitHub Step Summary
- updates/posts a single PR comment (marker-based) when a PR number is available

## Expected artifact naming
Default pattern: `test-results-*` (override via workflow input `artifact_name`).
