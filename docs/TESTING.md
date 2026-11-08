# Test history dashboard

Save `test-history.v1` JSON run records in a history directory.
Run `python -m scripts.test_history.render --history history --out dashboard`.
Optionally set `--repo owner/repository` to change GitHub commit links.
Open `dashboard/index.html` locally; it is self-contained and makes no network requests.
Read `dashboard/summary.md` for wave statistics, regressions, fixes, and flaky tests.

## CI publication

The `Test history` workflow publishes on pushes to `main`, every two hours,
and on manual dispatch. Test failures are recorded rather than failing publication;
infrastructure failures still fail the workflow. It uses the check and renderer
modules when available, with built-in record and Markdown fallbacks otherwise.

The orphan `test-history` branch contains `records/*.json` (`test-history.v1`),
`summary.md`, and `index.html` when the renderer is available. Each run also uploads
its JSON as an artifact and appends the summary to the GitHub Actions job summary.
Publication is serialized and retries rejected pushes.

Trigger a wave manually:

```sh
gh workflow run test-history.yml -f wave=1
```

Backfill completed main-branch CI runs with an authenticated GitHub CLI:

```sh
python -m scripts.test_history.backfill --limit 30 --dry-run
python -m scripts.test_history.backfill --limit 30 --out history
```

Backfill records are approximate: step conclusions supply suite verdicts, timestamps
supply durations, counts are null, and `source` is `backfill`. In-progress runs are
skipped. Filenames include the start time, commit prefix, and GitHub run ID, so
repeating a backfill overwrites the same records. The command only writes locally;
to publish, copy the resulting JSON into `records/` in a checkout of `test-history`,
regenerate its summary with `python -m scripts.test_history.render --history
<checkout>/records --out <checkout>` (or the backfill module's `--fallback-summary
--history <checkout>/records --out <checkout>`), then commit and push that branch.
