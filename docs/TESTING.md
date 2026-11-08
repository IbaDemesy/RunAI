# Test history dashboard

Save `test-history.v1` JSON run records in a history directory.
Run `python -m scripts.test_history.render --history history --out dashboard`.
Optionally set `--repo owner/repository` to change GitHub commit links.
Open `dashboard/index.html` locally; it is self-contained and makes no network requests.
Read `dashboard/summary.md` for wave statistics, regressions, fixes, and flaky tests.
