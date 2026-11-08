# RunAI — Target journeys

The reference spec for the night loop. Every team builds toward these three journeys.
Acceptance criteria live in [ACCEPTANCE.md](ACCEPTANCE.md) (ids `AC-xx`); open work lives in
[BACKLOG.md](BACKLOG.md) (ids `PB-xx`). Copy in "quotes" is the exact English text a judge
should read on screen; placeholders are in `<angle brackets>`.

## Shared vocabulary

| Term | Meaning | Where it lives today |
| --- | --- | --- |
| Framing | Short dialogue with Holo until all required slots are filled | `POST /api/framings`, `FramingSession.status` |
| Ready to confirm | Framing complete; the summary card is shown with a "Start" button | `FramingStatus.ready_to_confirm`, `FramingSession.summary` |
| Mission | 3 parallel steps launched after confirmation: `registration`, `accommodation`, `transport` | `GET /api/missions/{id}` (`mission.v2`), SSE `events.v1` |
| Agent lane | One column/card per step in the live view | `StepResult` in `MissionSnapshot.steps` |
| Pre-payment halt | The agent stops before any irreversible commitment | `StepStatus.stopped_before_commitment` + `StepResult.stop_point` (`consent`, `health_declaration`, `account_creation`, `submission`, `payment`) |
| Official-site handoff | Link that lets the runner finish the step themselves | `StepResult.url` (fallback: candidate `registration_url` / `official_url`) |
| Your trip | Final summary: race + stay + transport + total vs budget | `GET /api/missions/{id}/journey`, recap exports |
| Modes | `demo` (fixtures, ~30 s), `replay` (recorded real run), `live` (real partners) | `RUNAI_MODE` |

Partners showcased, used as attribution labels everywhere:

- **Holo** (H Company model `holo4-35b-a3b`): framing questions, slot extraction, rephrased agent questions.
- **Linkup**: race candidates with sources, start-URL precomputation, rules/race-sheet facts.
- **H agents** (`h/web-surfer-pro`): the 3 browser agents filling forms up to the halt.
- **Gladia** (solaria-1 live): voice input with live partials and mid-mission voice commands.
- **Devin**: built and repairs the product (shown in the pitch and README, not in the runtime UI).

Global rules for every screen (see AC-01..AC-06): English only; money as `€800`; dates as
`Sun 12 Apr 2026`; no empty list/join (`, ,` or trailing `·`); nothing is ever paid.

---

## J1 — Text framing, demo mode (primary jury demo, ~30 s)

**Persona.** Léa, 34, amateur runner based in Lyon. Wants a spring marathon abroad,
2 nights, budget €800 all-in, prefers train or plane. Types on a laptop.

**Mode.** `RUNAI_MODE=demo` (no keys needed) or `replay`. Must run end to end in ~30 s with
zero env vars beyond the mode (AC-60).

### Happy path

| # | Screen | User action | System response (exact copy) | Partner shown |
| --- | --- | --- | --- | --- |
| 1 | Home | Opens the app | Title "RunAI". Subtitle "Tell me your race. I prepare the whole trip — you only pay." Input placeholder "e.g. A spring marathon abroad, 2 nights, €800 from Lyon". 3 suggestion chips (each one a complete demo prompt). Mode badge "Demo data". | — |
| 2 | Home | Clicks a chip or types a request, presses "Send" | User bubble shows the text. Holo bubble types in: "Got it. Let me find matching races." | Holo |
| 3 | Framing | — | Holo asks only for missing slots, one at a time, e.g. "Where will you travel from?", "How many nights?", "What is your total budget in euros? Say 'no limit' if you are flexible." Each question offers 2–4 answer chips. Filled slots appear as chips: "Lyon", "2 nights", "€800". | Holo |
| 4 | Candidates | Answers the last question | Candidate cards (max 3): race name, city + country, date ("Sun 12 Apr 2026"), distances ("42 km · 10 km"), "Found by Linkup · <n> sources" with clickable source domains. Holo: "I found <n> races. Which one?" | Linkup (recorded) |
| 5 | Summary | Clicks "Choose" on a card | Summary card titled "Your plan": race, date, "From Lyon", "<n> nights (<check-in> → <check-out>)", "Budget €800", "Transport: train". Buttons "Start" and "Edit". Holo: "Ready when you are. Nothing will be paid." | Holo |
| 6 | Live view | Clicks "Start" | 3 agent lanes appear: "Race registration", "Accommodation", "Transport". Each lane: status pill, headline (e.g. "Filling the runner form"), current site domain, "Step <k>" counter, latest screenshot thumbnail, "H agent" badge. Header: "3 agents working in parallel". | H |
| 7 | Live view | Watches | Lanes update in real time via SSE. Results arrive as they land: "Hotel found — €240 for 2 nights", "Train Lyon → <city> — €118 return". | H, Linkup |
| 8 | Halt | — | Each lane ends on a halt card: "Prepared — not booked". "Stopped before: payment" (or consent / health declaration / account creation / submission). Button "Finish on official site ↗". | H |
| 9 | Your trip | Automatically after the last lane halts | "Your trip" card: race (name, date, entry fee), stay (hotel, nights, price), transport (out/back, price), "Total €<x> of €800 budget" with a green/amber/red indicator. 3 CTAs: "Finish registration on official site", "Finish hotel booking on official site", "Finish transport booking on official site". Exports: "Download PDF", "Add to calendar (.ics)". | All |

### Unhappy paths (J1)

| Case | Trigger | What the user must see |
| --- | --- | --- |
| No race found | Request matches no fixture | Holo: "I couldn't find a matching race. Try a race name, a city or a month." + the 3 suggestion chips again. Never a blank screen (AC-12). |
| Agent question | A lane needs input (e.g. distance choice) | Lane pill "Needs you". Holo-rephrased question in plain English with answer chips; answering resumes the lane (AC-33). |
| Anti-bot / login block | Fixture with a blocked step | Lane ends "Couldn't continue: the site asks for a login." + "Finish on official site ↗". Other lanes continue (AC-36). |
| Budget exceeded | Total > budget | "Total €<x> — €<over> over your €800 budget" in amber/red, plus "Cheapest option kept" note. No silent cap (AC-53). |
| Cancel | User clicks "Stop all" | All lanes show "Stopped by you". Summary still lists what was prepared so far. (AC-35) |

---

## J2 — Voice framing with Gladia

**Persona.** Karim, 41, trail runner in Bordeaux, speaks English with a French accent and
code-switches race names ("le Marathon de …"). Budget €600, 1 night, car or train.
Uses the app on a phone held in one hand.

**Mode.** `demo` with the Gladia fake, or `live` with `GLADIA_API_KEY` for the real stream.

### Happy path

| # | Screen | User action | System response (exact copy) | Partner shown |
| --- | --- | --- | --- | --- |
| 1 | Home | Taps the mic | Mic button turns red, label "Listening… · Gladia". | Gladia |
| 2 | Home | Speaks "A half marathon in May near Bordeaux, one night, six hundred euros" | Live partial transcript appears word by word in the input (grey), final transcript turns black. Race and city words recognised via custom vocabulary. | Gladia |
| 3 | Framing | Stops speaking (end of utterance) | Same as J1 steps 2–5; Holo questions can be answered by voice ("Bordeaux", "by train"). Each voice turn shows a small "Voice · Gladia" tag. | Gladia, Holo |
| 4 | Candidates / Summary | Says "the first one", then "start" | Candidate chosen, summary shown, mission launched (only after an explicit "start" or tap). | Holo |
| 5 | Live view | Says "pause the hotel" / "resume" / "stop everything" | Toast "Voice command: pause accommodation". The targeted lane shows "Paused by you" then resumes. | Gladia, H |
| 6 | Live view | Says "take the 10 km instead" | Toast "Sent to Race registration agent: take the 10 km instead". Lane headline updates. | Gladia, H |
| 7 | Halt / Your trip | — | Same as J1 steps 8–9. | All |

### Unhappy paths (J2)

| Case | What the user must see |
| --- | --- |
| Mic permission denied | "Microphone blocked. Allow it in your browser, or type instead." Text input stays usable (AC-41). |
| Noisy / empty transcript | "I didn't catch that. Try again or type it." No framing turn is created (AC-42). |
| Unrecognised voice command mid-mission | Toast "I heard '<text>'. Try: pause, resume, stop, or a correction for one agent." No action taken. |
| No race found / agent question / block / budget / cancel | Same as J1; questions can also be answered by voice. |

---

## J3 — Live mode on a real race

**Persona.** Sofia, 29, Lisbon-based runner planning a real race on an open Njuko or Klikego
registration page. Budget €500, 2 nights, plane. This is the "give us a race" jury moment.

**Mode.** `RUNAI_MODE=live` with H, Linkup and Gladia keys. Uses at most 3 H sessions
(2 orgs pooled). Real runs take 10–15 min per agent, so the live view must stay alive and
informative the whole time.

### Happy path

| # | Screen | User action | System response (exact copy) | Partner shown |
| --- | --- | --- | --- | --- |
| 1 | Home | Types or says the race | Mode badge "Live". Holo: "Searching the web for this race…" with a spinner "Linkup search". | Holo, Linkup |
| 2 | Candidates | — | Real candidate cards with official date, distances and "Found by Linkup · <n> sources" listing the real domains (clickable). Limitations shown in plain English, e.g. "Date not officially published yet". | Linkup |
| 3 | Summary | Chooses, confirms | Same as J1 step 5. | Holo |
| 4 | Live view | — | 3 lanes start real H sessions. Each lane: "H agent · web-surfer-pro", live screenshot refreshed every few seconds, current URL domain, "Step <k>", headline of the last action ("Typing the runner's birth date"). Link "Open H replay ↗" when available. | H |
| 5 | Live view | — | Linkup facts arrive in a side panel: "Bib pickup: <day, hours>", "Start area: <place>", each with its source link. | Linkup |
| 6 | Halt | — | Each lane: "Prepared — not booked · Stopped before: payment" + screenshot of the last page + "Finish on official site ↗" (the real page the agent reached). | H |
| 7 | Your trip | — | Same as J1 step 9 with real prices and real links. Footer: "Searched by Linkup · Driven by H agents · Voice by Gladia · Built with Devin". | All |

### Unhappy paths (J3)

| Case | What the user must see |
| --- | --- |
| No race found | Holo: "I couldn't find an official page for this race. Paste its website or try another name." |
| Agent question (H `AgentQuestion`) | Lane "Needs you" + Holo-rephrased question, e.g. "The form asks for your club licence number. Do you have one?" with "Yes, I'll type it" / "No licence". |
| Anti-bot / captcha / login wall | Lane: "Couldn't continue: the site shows a captcha." + last screenshot + "Finish on official site ↗". Never "Error 500", never a Python trace (AC-36). |
| H quota exhausted | Lane "Waiting for a free agent slot…" then starts; or "No agent slot available — finish on official site ↗" after timeout. |
| Budget exceeded | Same as J1. |
| Cancel | "Stop all" cancels every H session (no slot left busy) and shows "Stopped by you". |
| Partner outage | "Live search is unavailable right now. Showing a recorded run instead." and switch to replay (AC-61). |
