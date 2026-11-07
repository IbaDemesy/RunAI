# RunAI — Acceptance criteria

Each criterion has an id, the journeys it serves ([JOURNEYS.md](JOURNEYS.md)) and a
verification method:

- **API** — check a field of a JSON response or SSE event (name given).
- **pytest** — an automated test (existing file, or the file to create).
- **node** — a static shell test in `runai/app/static/tests/*.test.js` (run via `tests/test_static_shell.py`, needs `source ~/.nvm/nvm.sh`).
- **manual** — a step a human or the testing agent performs on the running app.

Owning teams are in [BACKLOG.md](BACKLOG.md). `runai/app/static/*` changes ship as `front-night` PRs.

## Global (all screens)

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-01 | No French anywhere user-visible: UI strings, Holo messages, framing questions, agent headlines, errors, exports, README. | J1 J2 J3 | pytest: new `tests/test_english_only.py` scanning `runai/**/*.py` string literals, static `.js/.html` and API fixtures for French markers (`é`, `è`, `à `, "Quel", "Combien", "Vérifiez", " le ", " la ", " des "); manual: read every screen of J1. |
| AC-02 | Money is always formatted `€800` (integers) or `€118.50` (cents), never `800.0`, `800 €` or `EUR 800`. | J1 J2 J3 | node: format helper test; API: backend-provided display strings (e.g. `summary.lines`) match `^€\d+(\.\d{2})?$` for amounts. |
| AC-03 | Dates are human-readable `Sun 12 Apr 2026`; ranges `Sat 11 → Mon 13 Apr 2026`; never ISO `2026-04-12` in UI text. | J1 J2 J3 | node: date helper test; manual. |
| AC-04 | No empty joins: no `, ,`, `· ·`, leading/trailing separators, `None`, `null`, `undefined`, `NaN` in any rendered text. | J1 J2 J3 | node: render fixtures with missing fields and assert regex `(, ,|· ·|^[,·]|[,·]$|None|null|undefined|NaN)` never matches. |
| AC-05 | Nothing is ever paid: no agent clicks a pay/confirm-payment control; every automated step ends `stopped_before_commitment`, `completed` (read-only), `failed` or `cancelled`. | J1 J2 J3 | pytest: existing safety tests (`runai/safety.py` `detect_stop_point`) + e2e demo mission asserts no step reaches a payment action. |
| AC-06 | Errors shown to the user are one plain-English sentence plus a next action; never a stack trace, HTTP code alone, or raw provider message. | J1 J2 J3 | API: `StepResult.data.error_user` set whenever `status == failed`; manual. |

## Home / framing

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-10 | Home shows title, one-line value proposition, input with English placeholder, 3 suggestion chips, mode badge (`Demo data` / `Replay` / `Live`). | J1 J2 J3 | manual; API: `GET /api/health` → `mode`. |
| AC-11 | No dead end in demo mode: every suggestion chip, followed by plausible answers to each Holo question (first answer chip each time), reaches `status == ready_to_confirm` within 6 turns. | J1 J2 | pytest: new `tests/test_demo_no_dead_end.py` iterating all chips against `RUNAI_MODE=demo`; API: `GET /api/framings/{id}` → `status`. |
| AC-12 | When no race is found, Holo says so in one sentence and re-offers the chips; the session stays `collecting`, never an empty candidate list without text. | J1 J3 | pytest: framing engine with empty `CandidateSearch` result → assistant turn text non-empty, `open_questions` non-empty. |
| AC-13 | Holo asks for one missing slot at a time and each question offers 2–4 answer chips (`FramingQuestion.choices`), except free-text-only slots (race name). | J1 J2 | API: `open_questions[0].choices` length; pytest on engine. |
| AC-14 | Filled slots are displayed as chips with formatted values (`Lyon`, `2 nights`, `€800`, `train`). | J1 J2 | node: slot chip rendering; manual. |
| AC-15 | A stale reply (old `revision`) returns 409 and the UI refetches without showing an error. | J1 J2 | pytest: existing framing API tests; manual. |
| AC-16 | Holo replies arrive in < 3 s (live) and < 1 s (demo). | J1 J3 | pytest (demo timing); manual stopwatch in live. |

## Candidates

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-20 | Each candidate card shows name, city + country, human date (or "Date not published yet"), distances (`42 km · 10 km`), and a "Choose" button. | J1 J3 | API: `candidates[]` fields `name`, `city`, `country`, `race_date`, `distances_km`; node: card render. |
| AC-21 | Partner attribution on the candidate card: "Found by Linkup · <n> sources" with clickable source domains (`RaceCandidate.sources`). | J1 J3 | API: `candidates[].sources` non-empty and `provenance.kind`; manual. |
| AC-22 | Candidate limitations are shown in plain English (`RaceCandidate.limitations[].message`). | J3 | API; manual. |
| AC-23 | At most 3 candidates are shown; choosing one is stable (re-rendering never reorders or swaps the selection). | J1 J3 | pytest: engine keeps `selected_candidate_id`; manual. |

## Summary / confirm

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-25 | "Your plan" card lists race, date, origin city, nights with check-in/check-out, budget, transport mode, with "Start" and "Edit". | J1 J2 J3 | API: `summary` fields (`race`, `origin_public`, `date_range`, `nights`, `budget_eur`, `transport_mode`, `lines`). |
| AC-26 | No mission starts without an explicit "Start" (tap or voice "start"); the same `idempotency_key` returns the same mission. | J1 J2 J3 | pytest: existing `assert_launchable` and confirm idempotency tests. |
| AC-27 | The origin is a public city/area, never an exact home address. | J1 J2 J3 | API: `summary.origin_public`; pytest on journey contract. |

## Live view (agent lanes)

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-30 | 3 lanes ("Race registration", "Accommodation", "Transport") appear within 2 s of "Start". | J1 J2 J3 | API: `GET /api/missions/{id}` → `steps[]` with 3 kinds; manual. |
| AC-31 | Each lane shows, per agent: status pill, current step headline, current site domain, step count. | J1 J2 J3 | API: `steps[].status`, `steps[].data.headline`, `steps[].data.current_url`, `steps[].data.step_count` (new field, see PB-07); SSE `step` events. |
| AC-32 | Each lane carries a partner badge ("H agent · web-surfer-pro" in live/replay, "H agent (demo)" in demo) and shows the latest screenshot when available. | J1 J3 | API: `GET /api/missions/{id}/steps/{kind}/screenshot` 200 in live/replay; manual. |
| AC-33 | Agent questions appear in the lane as a Holo-rephrased English question with answer chips; answering resumes the lane. | J1 J2 J3 | API: `questions[].display_text`, `choices`; `POST …/questions/{qid}/answer`; pytest. |
| AC-34 | Pause / resume per lane and "Stop all" work and are reflected within 2 s. | J1 J2 J3 | API: `steps[].status` `paused` / `running`; mission `cancelled`; pytest on fakes. |
| AC-35 | After "Stop all", lanes read "Stopped by you"; no H session stays active. | J1 J3 | pytest; manual: H quota shows 0 active after cancel. |
| AC-36 | A blocked lane (captcha, login, anti-bot, timeout) shows a one-line reason + "Finish on official site ↗"; the other lanes keep running. | J1 J3 | API: `steps[].status == failed`, `data.error_user`, `url`; pytest with a failing fake run. |
| AC-37 | Live updates stream over SSE with resume via `Last-Event-ID`; reconnect does not duplicate cards. | J1 J3 | pytest: existing events tests; manual reload mid-mission. |
| AC-38 | Live mode shows sources consulted (Linkup facts with links) as they arrive. | J3 | API: SSE `trace` / `journey_revised` events; manual. |

## Voice (Gladia)

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-40 | Mic button shows the attribution "Gladia" and a listening state; partial transcripts appear live, the final one replaces them. | J2 | manual (live key); node: partial/final rendering with a fake stream. |
| AC-41 | Mic permission denied → plain-English message; typing remains possible. | J2 | node; manual. |
| AC-42 | Empty or noise-only transcript creates no framing turn and shows "I didn't catch that." | J2 | pytest on `/api/transcribe` with empty audio; node. |
| AC-43 | Voice commands mid-mission (`pause <lane>`, `resume`, `stop everything`, free correction) map to the matching API call and show a confirmation toast. | J2 | pytest: command parser unit tests; API: `…/steps/{kind}/pause`, `…/message`. |
| AC-44 | Custom vocabulary includes running terms (marathon, half marathon, bib, 10K, trail) and the candidate race names. | J2 | pytest: Gladia config builder includes vocabulary. |

## Halt card (each step)

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-50 | Every finished step card states "Prepared — not booked". | J1 J2 J3 | node: halt card render for each `StepStatus`; manual. |
| AC-51 | Every halted card states the exact stop point in English: "Stopped before: payment / consent / health declaration / account creation / submission". | J1 J2 J3 | API: `steps[].stop_point` non-null when `status == stopped_before_commitment`; pytest. |
| AC-52 | Every step card has an official-site handoff link "Finish on official site ↗" pointing to `steps[].url` (fallback: candidate `registration_url` / `official_url`); never missing. | J1 J2 J3 | API: `steps[].url` non-null for halted/failed steps; pytest on demo fixtures. |
| AC-53 | Price shown per step (`price_eur`) and budget overflow flagged in amber/red with the overflow amount. | J1 J3 | API: `steps[].price_eur`, `budget`; node. |

## Your trip (final summary)

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-55 | "Your trip" shows race (name, date, entry fee), stay (name, nights, price), transport (outbound, return, price). | J1 J2 J3 | API: `GET /api/missions/{id}/journey`; node. |
| AC-56 | Total vs budget: "Total €<x> of €<budget> budget" with status colour; if no budget: "Total €<x>". | J1 J2 J3 | API: `MissionSnapshot.budget`; node. |
| AC-57 | 3 CTAs "Finish registration / hotel booking / transport booking on official site", each a working external link. | J1 J2 J3 | API: links from `steps[].url`; manual click. |
| AC-58 | Exports PDF / .ics / HTML use the same journey revision as the screen. | J1 J3 | pytest: existing recap export tests (`?revision=N`). |
| AC-59 | Footer attribution: "Searched by Linkup · Driven by H agents · Voice by Gladia · Built with Devin". | J1 J2 J3 | manual; node. |

## Modes and resilience

| Id | Criterion | Journeys | Verification |
| --- | --- | --- | --- |
| AC-60 | Replay and demo modes work with zero partner env vars (`RUNAI_MODE=replay` or `demo` only) and J1 completes in ≤ 45 s. | J1 | pytest: new e2e test running the app with an empty env; manual stopwatch. |
| AC-61 | In live mode, a partner outage degrades to a readable message and offers replay; the app never crashes. | J3 | pytest with failing fakes; API: `GET /api/health` → `providers.*`. |
| AC-62 | Public deployment (`RUNAI_PUBLIC=1`) requires basic auth outside simulated modes; `/api/health` stays open. | J3 | pytest: existing `tests` for `runai/app/auth.py`. |
| AC-63 | No secret appears in any API response, SSE event, trace or export. | J1 J2 J3 | pytest: existing redaction tests (`runai/redaction.py`), `tests/test_repo.py`. |
| AC-64 | Mobile: J1 is fully usable at 390×844 (no horizontal scroll, tap targets ≥ 44 px). | J1 J2 | manual (device emulation); Lighthouse accessibility ≥ 90. |
| AC-65 | Keyboard and screen reader: all controls reachable by Tab, lanes announce status changes (`aria-live`). | J1 | manual; axe audit with 0 critical issues. |
