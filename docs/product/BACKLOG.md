# RunAI — Product backlog (night loop)

Tickets for the Chief to route. Wave 1 has no jury or compliance report yet, so this first
cut is seeded from the jury weights in [../NOTATION.md](../NOTATION.md) (Computer Use 25,
Technical 25, Usefulness 20, Originality 15, UX 10, Demo 5), the gaps listed there, and a
read of the code on `main`. Source tags: **J** = simulated-jury lens (J-CU Computer Use,
J-TE Technical, J-UX UX/control, J-DE Demo), **C** = compliance (English-only, partner
usage, deliverables), **P** = product gap found while writing [JOURNEYS.md](JOURNEYS.md).
Later waves append jury-1/2/3 and compliance findings here with the same columns.

Priority: **P0** = blocks the primary jury demo (J1) or a hard rule; **P1** = strong score
impact; **P2** = polish. Status: `todo` / `in-progress` / `done` (update with PR link).
Teams: names from the night-loop master prompt.

| Id | Pri | Source | Ticket | Owning team | AC | Status |
| --- | --- | --- | --- | --- | --- | --- |
| PB-01 | P0 | C | Translate framing question templates in `runai/framing/engine.py` (`"Quel événement officiel…"`, `"Combien de nuits ?"`, …) and all Holo/`TemplatePhraser` copy to English. | Prompt engineering / Holo | AC-01, AC-13 | todo |
| PB-02 | P0 | C | Translate backend user-facing strings (errors, `Limitation.message`, headlines, `summary.lines`, log messages surfaced to UI, docstrings later) to English. | English translation | AC-01, AC-06 | todo |
| PB-03 | P0 | C | Translate static shell (`runai/app/static/*`) labels, placeholders, toasts to English (`front-night` PR). | Frontend | AC-01, AC-10 | todo |
| PB-04 | P0 | C | Add `tests/test_english_only.py` guard (French markers in code strings, static files, fixtures) and wire it into CI. | Tests & test history | AC-01 | todo |
| PB-05 | P0 | P | Demo no-dead-end test: every suggestion chip + first answer chip reaches `ready_to_confirm` in ≤ 6 turns; fix any fixture that stalls. | Tests & test history | AC-11 | todo |
| PB-06 | P0 | J-UX | Halt card: "Prepared — not booked" + "Stopped before: <stop point>" + "Finish on official site ↗" on every step (`front-night`). | Frontend | AC-50, AC-51, AC-52 | todo |
| PB-07 | P0 | J-CU | Expose `steps[].data.step_count` (H agent step counter) alongside existing `headline` and `current_url` in snapshot + SSE `step` events. | Backend / orchestration | AC-31 | todo |
| PB-08 | P0 | P | Guarantee `steps[].url` (official-site handoff) is non-null for every halted or failed step, with fallback to candidate `registration_url` / `official_url`; add pytest on demo fixtures. | Backend / orchestration | AC-52, AC-57 | todo |
| PB-09 | P0 | J-UX | "Your trip" summary: race + stay + transport + total vs budget + 3 official-site CTAs (`front-night`). | Frontend | AC-55, AC-56, AC-57 | todo |
| PB-10 | P0 | J-DE | Replay mode end to end with zero env vars; e2e pytest booting the app with an empty environment. | DevOps / release | AC-60 | todo |
| PB-11 | P0 | J-TE | Shared formatters: money `€800`, dates `Sun 12 Apr 2026`, null-safe joins; backend display strings and front helpers use them. | Backend / orchestration | AC-02, AC-03, AC-04 | todo |
| PB-12 | P0 | C | Hard rule audit: confirm no code path can click a payment control; e2e demo mission asserts every step ends before commitment. | Security & code review | AC-05 | todo |
| PB-13 | P1 | J-CU | Live view lane: partner badge, screenshot thumbnail refresh, "Open H replay ↗" via `share_session` public link. | H specialists | AC-32 | todo |
| PB-14 | P1 | J-CU | Per-platform runbooks (Njuko, Klikego, Accor, TAP) with Linkup-precomputed start URLs to cut steps (Booking test: 48 → 22). | H specialists | AC-31, AC-36 | todo |
| PB-15 | P1 | J-TE | Readable blocked-lane reasons (captcha, login wall, timeout, quota) in `data.error_user`; other lanes keep running. | Backend / orchestration | AC-06, AC-36 | todo |
| PB-16 | P1 | J-TE | H key pooling: wait for a free slot with "Waiting for a free agent slot…" status, then fall back to handoff link. | H specialists | AC-36 | todo |
| PB-17 | P1 | C | Candidate card attribution "Found by Linkup · <n> sources" with clickable domains (`front-night`). | Frontend | AC-21 | todo |
| PB-18 | P1 | J-CU | Linkup facts panel in live mode: bib pickup, start area, rules, each with source link (backend fields + `journey_revised`). | Linkup specialists | AC-38 | todo |
| PB-19 | P1 | C | Gladia mic: attribution label, live partials then final, custom running vocabulary + candidate names. | Gladia specialists | AC-40, AC-44 | todo |
| PB-20 | P1 | J-UX | Voice commands mid-mission (pause/resume/stop/correction) parser with unit tests and confirmation toasts. | Gladia specialists | AC-43 | todo |
| PB-21 | P1 | J-UX | Voice and mic error states: permission denied, empty transcript (no turn created). | Gladia specialists | AC-41, AC-42 | todo |
| PB-22 | P1 | J-UX | Holo rephrases every H `AgentQuestion` into one English question with 2–4 answer chips. | Prompt engineering / Holo | AC-33 | todo |
| PB-23 | P1 | P | No-race-found reply: one sentence + chips again; never an empty candidates screen. | Prompt engineering / Holo | AC-12 | todo |
| PB-24 | P1 | J-TE | Budget overflow computation exposed in `MissionSnapshot.budget` (total, budget, overflow, status colour). | Backend / orchestration | AC-53, AC-56 | todo |
| PB-25 | P1 | J-TE | Cancel guarantees 0 active H sessions after "Stop all" (pytest + quota check in live). | Backend / orchestration | AC-35 | todo |
| PB-26 | P1 | J-DE | Demo script + 3-min video following J1 then J3, with replay fallback. | Demo, pitch & docs | AC-60 | todo |
| PB-27 | P1 | C | README in English: pitch, modes, how to test live (Render URL + basic auth), partner usage section. | Demo, pitch & docs | AC-01, AC-62 | todo |
| PB-28 | P1 | C | Translate `docs/*.md` (NOTATION, V2, DEMO_ET_LIVRABLES, …) to English or move French drafts out of the judged path. | English translation | AC-01 | todo |
| PB-29 | P1 | J-TE | Run-history dashboard: verdict, duration, regressions per wave, success rate per platform (5 runs each). | Tests & test history | AC-60 | todo |
| PB-30 | P1 | P | Mission persistence and per-user history; replay a past mission from history. | Data & user request history | AC-60 | todo |
| PB-31 | P2 | J-UX | Mobile layout at 390×844, tap targets ≥ 44 px, lanes stacked. | Accessibility & mobile | AC-64 | todo |
| PB-32 | P2 | J-UX | Keyboard navigation and `aria-live` lane status announcements; axe 0 critical. | Accessibility & mobile | AC-65 | todo |
| PB-33 | P2 | J-TE | Latency and cost per mission (Linkup credits delta, H tokens) shown in a debug panel and logs. | Performance & observability | AC-16 | todo |
| PB-34 | P2 | J-TE | Prompt-injection review of framing input and page content fed back to Holo/H. | Security & code review | AC-63 | todo |
| PB-35 | P2 | J-UX | Design system spec: lane card, halt card, candidate card, trip card, partner badges. | UX/UI Design | AC-31, AC-50, AC-55 | todo |
| PB-36 | P2 | J-UX | Red-team scripts: vague request, unknown race, noisy voice, mid-mission contradiction; file tickets here. | Exploratory QA / red team | AC-11, AC-12, AC-42 | todo |
| PB-37 | P2 | C | Footer attribution "Searched by Linkup · Driven by H agents · Voice by Gladia · Built with Devin". | Frontend | AC-59 | todo |
| PB-38 | P2 | J-DE | Render deploy check after each merge wave (`/api/health`, replay J1 run on the public URL). | DevOps / release | AC-60, AC-62 | todo |
| PB-39 | P2 | C | Product spec upkeep: refresh this backlog from jury/compliance reports each wave. | Product / PM | — | todo |
