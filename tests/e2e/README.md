# Offline judge acceptance journeys

Run `source ~/.nvm/nvm.sh && .venv/bin/pytest -q tests/e2e` and
`.venv/bin/ruff check .` from the repository root.

Six journeys cover Milan, Lisbon and Tokyo, each through text and voice-labelled
HTTP framing turns. Voice here means an already-transcribed utterance, not a real
Gladia audio call. Demo providers use delay=0; sockets are forbidden and partner
keys are removed. No partner credits or payment operations are used.
Lisbon journeys correct the city slot to the fixture's canonical `Lisbonne`:
the current fixture candidate matcher does not recognize `Lisbon` as an alias.

The suite exercises framing replies, candidate selection, confirmation, SSE,
question answers, snapshots, journey exports and agent live-session history.
TestClient buffers SSE until EOF: an independent HTTP snapshot consumer answers
the first choice while the stream is open; afterwards the suite cross-checks
question_opened IDs against those answers. This does not test incremental
delivery timing. Mission HTTP journeys must finish within five seconds. PDF is
tested separately when a local Chrome renderer is installed, otherwise skipped.

## Tracked jury expectations

All tracking marks are non-strict xfails: an XPASS is a visible fix, not a failure.
IDs below are local W1 tracking IDs, not original jury ticket numbering.

| ID | Expected correct behaviour |
| --- | --- |
| JURY-W1-1 | Render the integral budget as €800, without 800.0, in the recap; preserve the numeric snapshot cap. |
| JURY-W1-2 | Omit the user-answer sentence when no answers exist. |
| JURY-W1-3 | Ask about the start pen only once per step. |
| JURY-W1-4 | A known race date resolves the period question; no unknown-period summary remains. |
| JURY-W1-5 | Parse “Milan marathon in April 2027” with Milan as city, never April. |
| JURY-W1-6 | Following “marathon from Lyon” with Lisbon offers the nearest demo fixture instead of dead-ending. |
| JURY-W1-7 | Journey and recap consistently reflect the race, selected hotel and train shown in snapshot cards (jury-2 #5). |

## Tracked backend gap

GAP-W1-1 expects every stop-point step in the HTTP mission snapshot to expose a
non-empty `human_action`. It is tracked separately as a non-strict xfail because
mission.v2 currently serializes StepResult without that field. The six normal
journeys retain the remaining safety and consistency assertions.

No UI rendering or real partner integration is verified by these tests.
