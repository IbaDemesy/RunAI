## What
Summary of the change.

## How to test
Commands or steps to verify.

## Security checklist (see `docs/SECURITY_REVIEW.md`)
- [ ] No secrets or `.env` in the diff; `secret:org:*` bound via env only
- [ ] New env vars documented in `.env.example` / README
- [ ] Halts untouched: `guard_task`, `detect_stop_point`, `HumanQuestionRegistry` refusals, `FORBIDDEN_HOSTS`
- [ ] No new `except Exception` without `# noqa: BLE001 - <reason>`
- [ ] No real partner API call (H / Gladia / Linkup) in `pytest`
- [ ] English only (code, strings, prompts, commits)
- [ ] No change under `runai/app/static/` unless labelled `front-night`
- [ ] Static `.js`: no `classList` / `document.body`; no "Milan" / "Paris" / "42.195"
- [ ] SSE / public payloads: no new session secrets, policy reasoning or env values
- [ ] `ruff check .` and `pytest -q` pass
