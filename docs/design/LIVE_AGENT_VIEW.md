# Live agent workspace — "Preparations in progress"

Status: design spec (wave 1). Owner of the implementation: Frontend (`runai/app/static/*`, Mathieu).
Static mockup: [`mockups/live-view.html`](mockups/live-view.html) (opens from `file://`, no network, fake data).

## Goal

Once framing is done, the mission screen becomes **one minimal live workspace** where a judge sees, at a glance:

- **what each H agent is doing right now** (factual headline, page, freshness, step counter),
- **which partner did what** (Linkup found the race, Holo framed it, Gladia heard the voice, H drives the browsers),
- **that RunAI never pays** (every lane ends at a "Prepared — not booked" card with the stop point).

Principles: one screen, no tabs for the live part; three compact lanes; one large screenshot pane for the selected
lane; facts over chatter (`step.data.headline`, never `last_action`); a failed lane never hides its siblings.

## Wireframe (desktop ≥ 900 px)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ RunAI · Lakeside Half · Sun 12 Apr                                   [LIVE] ● Connected  │
│ [Found by Linkup · 1.8 s · 3 sources ▸] [Framed by Holo] [Voice by Gladia]               │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌ OPEN QUESTION (Stay) ────────────────────────────────────────────────────────────────┐ │
│ │ Two rooms left under budget. Which one?   [Hotel du Lac · €118] [Les Pins · €96] [__] │ │
│ └──────────────────────────────────────────────────────────────────────────────────────┘ │
│ ┌ Registration ──────────┐ ┌ Stay ───────────────────┐ ┌ Transport ───────────────────┐ │
│ │ ● Running   H web-sur… │ │ ? Needs you   H web-su… │ │ ■ Prepared — not booked      │ │
│ │ Filling the runner     │ │ Waiting for your answer │ │ Train 07:42 → 10:15 · €64    │ │
│ │ form                   │ │ booking.com · Hotels…   │ │ Stopped at: payment page     │ │
│ │ njuko.com · Entry form │ │ updated 2 min ago       │ │ step 31/40 · 9 min 12 s      │ │
│ │ updated 4 s ago        │ │ step 22/40 · 6 min 03 s │ │ [Finish on the official site]│ │
│ │ step 14/40 · 3 min 40 s│ │ [Pause] [Cancel]        │ │ [H replay] [Watch replay]    │ │
│ │ [Pause] [Cancel]       │ │ [Watch live] [H replay] │ │                              │ │
│ └────────── selected ────┘ └─────────────────────────┘ └──────────────────────────────┘ │
│ ┌ Registration · Latest observation ───────────────────────────────────────────────────┐ │
│ │ ┌──────────────────────────────────────────────────────────────────────────────────┐ │ │
│ │ │                          large screenshot (16:10)                                │ │ │
│ │ └──────────────────────────────────────────────────────────────────────────────────┘ │ │
│ │ Latest observation · 12:04:31 · not a video stream          [Watch live] [H replay]  │ │
│ │ [thumb r12][thumb r13][thumb r14 ●]                                                  │ │
│ │ ▸ History (9 events)                                                                 │ │
│ └──────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Mobile (≤ 640 px): one column in this order — top strip (badges wrap) → **open question** → lanes stacked →
screenshot pane (height capped at 42 vh, `object-fit: contain`) → thumbnails (horizontal scroll) → history.

## Components

| # | Element | Behaviour |
|---|---|---|
| A | Top strip | Race name + date, mode badge (`LIVE` / `DEMO` / `REPLAY`), connection health dot. Partner chips: Linkup (always when a search ran, expandable to the query + source domains), Holo (always after framing), Gladia (only if the user spoke). |
| B | Open question card | Shown above the lanes whenever `questions[status=open]` exists; reuses the existing answer flow. On mobile it is the first thing after the strip. |
| C | Lane (×3: Registration / Stay / Transport) | Status chip, partner badge, headline, domain + page title, freshness age, step counter + elapsed, controls, links. Click/Enter selects the lane for pane D. `search` step is not a lane (it feeds chip A). |
| D | Screenshot pane | One pane for the selected lane (default: first `running` lane, else first lane with a capture). Large image, caption with capture time and "not a video stream", thumbnail strip of previous revisions, collapsed history. |
| E | Result card | Replaces the live body of a lane once it is `stopped_before_commitment` / `completed`; keeps headline, price, stop point and the "Finish on the official site" link. Never removed by sibling failures. |

## Lane status states (8)

| State | Source | Chip label | Chip style | Controls | Pane caption |
|---|---|---|---|---|---|
| `pending` | `step.status = pending` | Queued | muted outline | Cancel | "No observation yet" |
| `running` | `step.status = running` | Running | sun dot, pulsing | Pause, Cancel | "Latest observation · hh:mm:ss · not a video stream" |
| `pause_requested` | `NEEDED: step.data.control.requested = "pause"` while `status = running` | Pausing… | sun outline | (disabled) Resume, Cancel | same as running |
| `paused` | `step.status = paused` (set only once H reports `paused`) | Paused (confirmed by H) | haze | Resume, Cancel | "Paused · last observation hh:mm:ss" |
| `waiting_for_user` | `step.status = waiting_for_user` + open question with same `step` | Needs you | sun fill | Pause, Cancel | "Waiting for your answer" |
| `stopped_before_commitment` | `step.status = stopped_before_commitment` | Prepared — not booked | ok | — | "Final capture · stopped at: <stop_point>" |
| `completed` | `step.status = completed` | Done | ok | — | "Final capture" |
| `failed` | `step.status = failed` | Couldn't finish | bad | Retry (future) | "Last capture before the error" + `step.error` |

Rules:
- **Connection health ≠ observation freshness.** The dot in A reflects the SSE stream (green: event or heartbeat
  < 20 s ago; amber: reconnecting; red: > 45 s). The "updated N s ago" in each lane reflects the last new
  screenshot/observation of that H agent only.
- **Freshness age** = now − time of the last `browser_observation.revision` change (client-side timestamp when the
  revision increments, or `NEEDED: browser_observation.at`); fallback: last `data.history[].at`.
  Age turns amber after 60 s while `running` ("no new page for 1 min — the agent may be thinking").
- **Stopped lanes keep their result card**: headline, price (`price_eur`), "Stopped at: <stop_point label>",
  "Finish on the official site". Stop point labels: consent → "consent box", health_declaration → "health
  declaration", account_creation → "account creation", submission → "final submit", payment → "payment page".
- **Failed lanes never hide sibling results**: a failed lane collapses to its chip + friendly error + manual link;
  other lanes and the pane keep rendering. Mission-level `error` is shown as a banner under A, not instead of lanes.
- **Sensitive captures**: when the observed page is a sensitive form (`NEEDED: browser_observation.sensitive`),
  the image is blurred and replaced by a "Show capture" toggle; thumbnails of that revision are blurred too.
- **Pause / Resume / Cancel per lane**: Pause → optimistic `Pausing…` until the snapshot reports `paused`.
  Cancel asks a one-line confirmation ("Stop this agent? Other lanes keep running.").
- **Links**: "Watch live" only while active and when `live_view_url` (or `share_url`) is HTTPS; "H replay"
  when `agent_view_url` exists, with the hint "needs an H login" unless `share_url` is present (then the
  link uses `share_url` and the hint disappears).

## Field map

Every element in the mockup, with its source. `mission` = `GET /api/missions/{id}` snapshot (`MissionSnapshot`),
`step` = an item of `mission.steps[]` (`StepResult`, built by `MissionService._snapshot_steps`).

| Element (mockup `data-field`) | Source |
|---|---|
| Race name | `mission.race.name` |
| Race date | `mission.race.date` |
| Mode badge | `mission.mode` (`live` / `demo` / `replay`) |
| Connection dot | SSE `/api/missions/{id}/events` liveness: any event, or `NEEDED: heartbeat` event |
| Event cursor (resume after reconnect) | existing: SSE `id: <mission_id>:<sequence>` + `Last-Event-ID`; `mission.sequence` |
| Linkup chip "Found by Linkup · 1.8 s · 3 sources" | `NEEDED: mission.linkup_call {query, latency_ms, sources[]}` |
| Linkup chip expanded (query, source domains) | `NEEDED: mission.linkup_call.query`, `.sources[].url/.title` |
| Holo chip "Framed by Holo" | `NEEDED: mission.framed_by {provider, model}` (e.g. `holo` / `template` fallback) |
| Gladia chip "Voice by Gladia" (conditional) | `NEEDED: mission.voice {provider: "gladia", utterances}`; hidden when absent |
| Mission error banner | `mission.error`, `mission.limitations[].message` |
| Open question text | `mission.questions[status=open].text` |
| Open question lane label | `mission.questions[].step` |
| Open question choices | `mission.questions[].choices[]` |
| Open question free answer | POST `/api/missions/{id}/questions/{question_id}/answer` with `revision` |
| Lane title | `step.kind` (`registration` / `accommodation` → "Stay" / `transport`) |
| Status chip | `step.status` (+ `NEEDED: step.data.control` for `pause_requested`) |
| Partner badge "H web-surfer-pro" | `NEEDED: step.data.provider {name: "H", agent: "h/web-surfer-pro"}` |
| Headline | `step.data.headline` (fallback `step.summary`; never `last_action`) |
| Current domain | hostname of `step.data.browser_observation.url` (fallback `step.data.current_url`) |
| Page title | `step.data.browser_observation.title` |
| "updated 4 s ago" | `step.data.browser_observation.revision` change time (client) or `NEEDED: browser_observation.at`; fallback last `step.data.history[].at` |
| "step 14/40" | `NEEDED: step.data.step_index`, `step.data.max_steps` |
| Elapsed "3 min 40 s" | `NEEDED: step.data.started_at` (client computes elapsed; frozen at `ended_at`) |
| Pause / Resume buttons | POST `/api/missions/{id}/steps/{kind}/pause` · `/resume` |
| Cancel button (per lane) | `NEEDED: POST /api/missions/{id}/steps/{kind}/cancel` (only mission-wide `/cancel` exists) |
| "Watch live" link | `step.live_view_url` (HTTPS only) → `NEEDED: step.share_url` |
| "H replay" link | `step.agent_view_url` (needs H login) → `step.share_url` when present |
| "needs an H login" hint | shown when `step.agent_view_url` and no `step.share_url` |
| "Finish on the official site" | `step.data.manual_url` \|\| `step.url` |
| Result price | `step.price_eur` |
| Result summary | `step.summary` |
| "Stopped at: payment page" | `step.stop_point` |
| Friendly error (failed lane) | `step.error` / `step.data.headline` (already `friendly_error`) |
| Screenshot image | `GET /api/missions/{id}/steps/{kind}/screenshot?v=<browser_observation.revision>` |
| Caption time "12:04:31" | `NEEDED: browser_observation.at` (fallback: client time of revision change) |
| Thumbnail strip | `NEEDED: screenshot?rev=<n>` history (keep last N refs per run) |
| "Show capture" toggle | `NEEDED: browser_observation.sensitive` |
| History list (time + message) | `step.data.history[].at`, `.message` (fallback `.type`) |
| H session id (technical details) | `step.h_session_id` |

## NEEDED — handed to Backend (12)

| # | Field | Why |
|---|---|---|
| 1 | `mission.linkup_call {query, latency_ms, sources[{url,title}]}` | Makes Linkup's contribution visible and measurable in the top strip (jury P0). |
| 2 | `mission.framed_by {provider, model}` | Shows Holo did the framing, and honestly shows the template fallback in demo/no-key mode. |
| 3 | `mission.voice {provider, utterances}` | Gladia chip must only appear when voice was really used. |
| 4 | `step.data.provider {name, agent}` | Partner badge per lane ("H web-surfer-pro"), future-proof if a lane uses another agent. |
| 5 | `step.data.step_index` + `step.data.max_steps` | "step 14/40" progress; `run.metrics["steps"]` exists in the runner but is not copied to `step.data`. |
| 6 | `step.data.started_at` / `ended_at` | Elapsed time per lane that survives reloads (client clocks drift and reset). |
| 7 | `step.share_url` | Public no-login H replay/live link (`sessions.share_session`); `agent_view_url` needs an H login. |
| 8 | `step.data.browser_observation.at` | Exact capture time for the caption and freshness age, independent of client reload. |
| 9 | screenshot history: `?rev=<n>` + `browser_observation.revisions[]` | Thumbnail strip; today only the latest screenshot ref is kept. |
| 10 | `step.data.browser_observation.sensitive` | Hide health-declaration / identity forms behind "Show capture". |
| 11 | `step.data.control {requested, requested_at}` + `POST …/steps/{kind}/cancel` | Distinguish "pause requested" from "paused (confirmed by H)"; cancel one lane without killing the others. |
| 12 | named SSE `heartbeat` event (`{at, sequence}`) every 15 s | Current keepalive is an SSE comment, invisible to `EventSource`, so the client cannot tell "connected but idle" from "stalled". |

Already available (no backend work): event sequence id (`id: <mission_id>:<n>`, `Last-Event-ID`, `mission.sequence`),
headline, browser_observation url/title/revision, history, stop_point, manual_url, live_view_url, agent_view_url,
per-step pause/resume, screenshot endpoint.

## Copy (English, final)

- Section title: "Preparations in progress"
- Caption: "Latest observation · {time} · not a video stream"
- Empty pane: "No observation yet — the agent is opening the browser."
- Freshness: "updated {n} s ago" / "updated {n} min ago" / amber "no new page for {n} min"
- Result: "Prepared — not booked" · "Stopped at: {stop point}" · "RunAI never pays."
- Failed: "Couldn't finish — you can finish on the official site."
- Hint: "H replay needs an H login."
