# RunAI

**Say your race; RunAI prepares the registration, hotel and transport, stopping before payment.**

Computer Use Agents Hackathon (H Company x 42AI), November 7-8, 2026.

## What it does

Voice -> Holo framing -> Linkup official race sheet -> explicit confirmation ->
three H `h/web-surfer-pro` agents in parallel -> **pre-payment halt**.

Describe your race and trip, correct missing details, choose a sourced race and
confirm the summary before any agent starts. Follow registration, accommodation
and transport in live browser views, then review the journey timeline and
HTML/PDF/ICS exports. **RunAI never pays or makes a binding booking.**

## Partners and how each is showcased

| Partner | Showcase |
| --- | --- |
| H Company | Three browser agents, the Holo4 framing model and live views of their work. |
| Gladia | `solaria-1` live transcription with custom vocabulary and multilingual code-switching. No TTS. |
| Linkup | Structured search produces a sourced official race sheet, not an invented event. |
| Devin | Built the app and CI; a 16-agent night exploration loop informed the design. The [self-repair plan](docs/DEVIN.md) describes future trace-to-runbook fixes, not an already deployed repair service. |

[Partner resources](Infos/README.md) | [Demo and deliverables](docs/DEMO_ET_LIVRABLES.md) | [V2 technical details](docs/V2.md)

## Quickstart

From the repository root, with Python 3.11+ installed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

For live mode, configure these variable names in your local `.env`:
`HAI_API_KEY`, `GLADIA_API_KEY`, `LINKUP_API_KEY`.
Optional extra H accounts use `HAI_API_KEY_2`, `HAI_API_KEY_3`, etc., with no
numbering gaps. Linkup reads only `LINKUP_API_KEY`, not numbered variants.
Never commit credentials or `.env`. Optional settings are documented in
[.env.example](.env.example).

## Run it

Choose a mode explicitly, from the repository root:

```bash
RUNAI_MODE=live .venv/bin/python -m runai.app
RUNAI_MODE=demo .venv/bin/python -m runai.app
RUNAI_MODE=replay .venv/bin/python -m runai.app
```

Open `http://127.0.0.1:8000`; `RUNAI_APP_HOST` and `RUNAI_APP_PORT` override
the local bind address.

| Mode | Behavior |
| --- | --- |
| `live` | Real Linkup, H and Gladia calls. Missing keys produce explicit unavailable errors, never a silent demo fallback. |
| `demo` | Clearly labeled fixture candidates and simulated agents/transcription. Unsupported criteria produce a limitation, not a substitute invented race. |
| `replay` | **Fallback demo:** the default recorded trace runs without keys or extra environment variables and makes no provider calls. Results are labeled replay, not live. |

To select a specific `replay.v1` trace instead of the default:

```bash
RUNAI_MODE=replay RUNAI_REPLAY_TRACE=<path> .venv/bin/python -m runai.app
```

The default trace is `fixtures/replay/demo-marathon.replay.json`, also available in
Render's repository checkout; regenerate it offline with `python -m scripts.record_replay`.
For a live recording, start `RUNAI_MODE=live .venv/bin/python -m runai.app`, confirm a
framing and answer its questions until the mission is terminal, then run
`curl --fail --user "$RUNAI_BASIC_AUTH" "http://127.0.0.1:8000/api/missions/$MISSION_ID/replay.json" --output live.replay.json`
(set `MISSION_ID`; omit `--user` if authentication is disabled). Exports redact
configured provider secrets and structured personal fields, emails and phone numbers;
review free-text recordings before sharing.

[render.yaml](render.yaml) defines the Render web services, their health check at
`/api/health`, and this production entrypoint:

```bash
uvicorn runai.app.server:create_app --factory --host 0.0.0.0 --port $PORT
```

See [Deploy on Render](#deploy-on-render) for the services and their settings.

## How to test it live

**Deployment: `RENDER_URL` (to be filled in by DevOps).**

The operator configures `RUNAI_BASIC_AUTH` as a username/password pair; obtain
access privately, never in this repository. With `RUNAI_PUBLIC=1`, live startup
refuses to run without basic auth, protecting provider credits.

1. Open `RENDER_URL`, sign in if prompted, and allow microphone access. Describe
   a supported race and trip by voice (or type it).
2. Check the sourced race sheet and framing fields, correct missing information,
   then explicitly confirm. Watch the three covered agent tasks and live views.
3. Review each result and the journey recap. The halt leaves the payment or
   binding confirmation step untouched and reports the prepared state for human
   review. No charge, final booking, account creation or binding submission is made.

If provider access fails during judging, use a `RUNAI_MODE=replay` deployment or the
local replay command above, and present it explicitly as a replay.

## Tests

Offline checks from the repository root (Node 24 must be on pytest's PATH):

```bash
source ~/.nvm/nvm.sh
.venv/bin/ruff check .
.venv/bin/pytest -q
node --test web/flyover/tests/*.test.js tests/contracts/*.test.js runai/app/static/tests/*.test.js web/voice/tests/*.test.js
for script in runai/app/static/*.js web/flyover/*.js web/voice/voice-input.js; do node --check "$script" || break; done
```

UX tests replay patches against commit `97265c6`; the clone must include that
history. CI uses a full checkout and installs Node 24.

Optional live smoke tests require the corresponding keys, network access and
provider credits (the H test can take about three minutes):

```bash
python scripts/test_h.py
python scripts/test_gladia.py
python scripts/test_gladia.py mon_audio.mp3
python scripts/test_linkup.py
```

CI runs Ruff and offline pytest on pull requests and pushes to main. The smoke
workflow runs selected real-provider checks separately to avoid spending credits
on documentation PRs.

## Deploy on Render

`render.yaml` is a Render Blueprint synced from `main` (Render → **New → Blueprint**, pick this repo and `main`). Every push to `main` redeploys both services (`autoDeploy: true`). Each runs a single free instance, because missions live in server memory.

| Service | Mode | Access | Partner credits |
| --- | --- | --- | --- |
| `runai-demo` | `RUNAI_MODE=demo` (simulated search, agents and voice) | Public, no password: the URL to give judges | None |
| `runai` | `RUNAI_MODE=live` (real H, Linkup, Gladia) | HTTP Basic auth (`RUNAI_BASIC_AUTH`) | Yes |

Set these in the Render dashboard for `runai` (all `sync: false`, never committed):

- `RUNAI_BASIC_AUTH`: `user:password`. Required: both services set `RUNAI_PUBLIC=1`, and with it the app refuses to start in a non-simulated mode unless `RUNAI_BASIC_AUTH` is set, so nobody can spend the credits anonymously.
- `HAI_API_KEY`, and optionally `HAI_API_KEY_2`: the H runner pools every `HAI_API_KEY[_N]` key (one H organization each) and picks the key with free quota. `RUNAI_H_MAX_CONCURRENCY=3` caps each key, but the mission service currently applies the same value as a global cap, so a second key adds failover, not more than 3 parallel H sessions.
- `LINKUP_API_KEY`, `GLADIA_API_KEY` (voice is optional). `LINKUP_API_KEY_2` and `GLADIA_API_KEY_2` are declared as backups; the app does not read them yet, so to switch, copy the backup into the primary key.

Credit guards on `runai`: `RUNAI_H_MAX_STEPS=40`, `RUNAI_H_MAX_TIME_S=600`. Traces go to `RUNAI_TRACES_DIR=/tmp/runai-traces`; the free disk is ephemeral, so they are lost on every redeploy or restart. `runai-demo` declares no API key.

`/api/health` stays open (no password) on both services for the Render health check. Free instances sleep after about 15 minutes without traffic (wake-up takes about a minute and drops running missions): open the page before a demo.

Authentication failure counters also live in process memory and reset on
restart. `/api/health` is the only public route when
authentication is enabled; static assets, `/demo/live`, event streams and
screenshots require credentials. Set `RUNAI_BASIC_AUTH=user:password` in Render's
secret environment settings; for separate credentials use a comma-separated list
such as `user:password,user2:password2` (commas cannot be part of a password).
After five failed authentication attempts within 60 seconds, that client IP is
blocked with HTTP 429 and a `Retry-After` header until the window expires. The
first `X-Forwarded-For` hop identifies clients behind Render's TLS proxy; use this
deployment only behind a trusted proxy that supplies that header.

Security headers apply to authenticated and rejected responses alike, and API
responses use `Cache-Control: no-store`. Content Security Policy defaults to
`Content-Security-Policy-Report-Only` (`RUNAI_CSP_ENFORCE=0`); set
`RUNAI_CSP_ENFORCE=1` to send an enforcing `Content-Security-Policy` instead.

## Architecture

| Directory | Responsibility |
| --- | --- |
| `runai/app/` | Web server, auth, provider modes, missions and browser UI. |
| `runai/framing/` | Holo-assisted intent framing, clarification and launch confirmation. |
| `runai/h/` | H browser-agent lifecycle, events and human questions. |
| `runai/search/` | Linkup race discovery, structured sheets and source checks. |
| `runai/voice/` | Gladia audio transcription, vocabulary and voice commands. |
| `runai/journey/` | Shared journey planning from task results. |
| `runai/planning/` | Evidence handling and recap adaptation. |
| `runai/quote/` | Registration quote extraction and verification. |
| `runai/logistics/` | Eligibility, durations, timeline rules and calendar data. |
| `runai/recap/` | Journey recap rendering and HTML/PDF/ICS exports. |
| `runai/coach/` | Runner-level assessment and training recommendations. |
| `runai/contracts/` | Shared typed framing, mission and journey contracts. |
| `web/` | Flyover and voice frontend modules and tests. |
| `tests/` | Offline Python, contract and regression tests. |
| `scripts/` | Partner API smoke tests. |
| `docs/` | Design, integration notes, demo and pitch guides. |

Shared configuration, models, safety checks and redaction live directly in
`runai/`.

## Limits

Framing, missions, idempotency, SSE events and export revisions are stored in
memory. Automation is limited to **Njuko / Accor / Trenitalia** (rail and Italian
coverage for the latter). Other platforms and transport are manual, with an
official link when known; Booking.com and TAP are excluded from automation.
French/English extraction is heuristic and partial: correct fields in framing.
The default profile is fictional. No payment, booking, account, consent, health
declaration or binding submission is automated. Gladia transcribes speech;
**there is no text-to-speech (TTS)**. Journey data not supplied structurally
remains unknown. JSONL traces may be written to disk, but are not persistent
mission storage.

## Team

Computer Use Agents Hackathon, November 7-8, 2026.

| Name | Role | GitHub |
| --- | --- | --- |
| To fill in | To fill in | To fill in |
| To fill in | To fill in | To fill in |
