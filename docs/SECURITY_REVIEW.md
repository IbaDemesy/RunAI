# Security review checklist

Every PR to `main` must pass this checklist. The security reviewer posts one
comment per PR ending with a verdict line:

`Security review: PASS | PASS with nits | BLOCK`

A PR is **BLOCKED** only for: committed secrets, a removed or weakened halt,
French strings in new code, or changes under `runai/app/static/` without the
`front-night` label. Everything else is a nit.

## 1. Secrets
- [ ] No API key, token, password or `.env` file in the diff (including fixtures, logs and screenshots).
- [ ] Partner keys (`HAI_API_KEY[_N]`, `GLADIA_API_KEY[_N]`, `LINKUP_API_KEY[_N]`) are read from the environment only; in Devin sessions they are bound as `secret:org:*` through the exec `env`, never written to files.
- [ ] New environment variables are documented in `.env.example` and the README, with placeholder values only.

## 2. Safety halts (never weakened)
- [ ] The pre-payment / account creation / consent / final submission halts are untouched: `guard_task` and `detect_stop_point` in `runai/safety.py`.
- [ ] `HumanQuestionRegistry` (`runai/h/human_questions.py`) still refuses forbidden answers (payment data, passwords, consent).
- [ ] `FORBIDDEN_HOSTS` (`runai/app/providers.py`) has no entry removed.
- [ ] No code path performs a payment or submits a final order.

## 3. Error handling
- [ ] No new bare `except Exception` without `# noqa: BLE001 - <reason>`.
- [ ] Errors shown to the user are readable and do not leak stack traces, env values or keys.

## 4. Tests and partner credits
- [ ] `.venv/bin/ruff check .` passes.
- [ ] `source ~/.nvm/nvm.sh && .venv/bin/pytest -q` passes (reinstall `requirements.txt` if imports fail).
- [ ] No real partner API call (H, Gladia, Linkup) inside `pytest`: fakes only. Real calls live in `scripts/`.

## 5. Language
- [ ] English only in new code, UI strings, prompts, docs, commit messages and the PR.

## 6. Frontend ownership
- [ ] No change under `runai/app/static/` unless the PR has the `front-night` label (those PRs are not auto-merged).
- [ ] Static `.js`: no `classList` or `document.body` (use `className +=` and optional chaining).
- [ ] Static files contain no "Milan", "Paris" or "42.195".

## 7. Public payloads (SSE / API)
- [ ] SSE and public JSON payloads expose no new session secrets (no `agent_view_url` beyond existing fields), no policy/guard reasoning text and no environment values.
- [ ] Prompt injection: text coming from web pages, H agents or users is never executed or used to bypass the halts above.
