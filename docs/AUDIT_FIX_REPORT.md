# Audit fix integration report

## Delivery and gate

Branch: `integration/audit-fix`, based on `origin/main` (audit baseline d320c2a).
Six PR branches integrated locally, in order: W1 #139, W2 #138, W3 #140, W4 #137, W5 #141, W7 #136.
No PR opened, no merge to main, no history rewrite.

Latest user instruction: skip tests and deliver the branch immediately.
Integration pytest was started, then cancelled at approximately 9%; **no full integration pytest result**.
Ruff had already completed: `All checks passed!`
Node had already completed: `tests 123; pass 123; fail 0`.
No additional tests were run after the skip instruction.
Baseline reported by implementers: pytest 2078 passed, 3 skipped, 12 xfailed, 2 xpassed; Node 120 pass.
Existing expected failures include SSE contract gaps, AC-02, human-action snapshot and jury framing/transport gaps; no integrated final inventory was obtained.

Independent R1–R4 reviews: **non terminée**. No fetched PR review contains the required per-ID APPROUVÉ verdict.
The integration gate is **NOT satisfied** (full pytest cancelled, independent reviews incomplete).
The statuses below retain implementer claims in a separate column. Claims of completion are conservatively PARTIEL until required review and integration evidence exist; this is not a claim that their code is unfinished.

## Conflict resolution

- W3 engine: retained W3 origin normalization, slot masking and origin-question Holo suppression; composed W1 and W3 address masking for Holo input and persisted user turn.
- W7 auth test: kept W2 sha256 import plus W7 acceptance tag.
- W7 e2e: retained W5 removed budget xfail and precise strict transport-fare xfail; other W7 strict-marker changes retained.
- W7 NOTATION/VOICE_INPUT/BACKLOG: retained W5 updated implementation caveats, English edited rows and existing scoped English guard; other nonconflicting W7 documentation/test changes retained.
- Conflict marker scan `rg -n '^(<<<<<<<|>>>>>>>)' .`: no matches.
- No visual/browser verification, Windows verification or live partner API calls.

## Architecture summary

1. FastAPI serves framing, missions, voice and static interfaces.
2. Framing maintains structured slots and asks focused follow-up questions.
3. Local extraction and optional Holo help interpret user requests.
4. Linkup supplies sourced race discovery and provenance.
5. Explicit confirmation launches the mission orchestrator.
6. H lifecycle/runner coordinate browser steps and organization slot limits.
7. Human-question and safety guards stop before commitments.
8. Mission state and event history support SSE and replay.
9. Journey planning combines race, accommodation, transport and logistics.
10. HTML/PDF/ICS exports and Explore render the resulting plan.

## Per-ID register

Tests below are implementer-reported evidence from PR descriptions, not a completed integration rerun.

| ID | Statut | Déclaration PR | PR | Tests reported | Review | Remaining risk |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | PARTIEL | DONE | #139 | `tests/test_h_runner.py` (host drift: stripe/paypal/booking/off-allowlist -> `cancel` + slot released + `stopped_before_commitment`; allowed subdomains and Njuko/Accor/Trenitalia redirects -> no cancel). Red: 26 failed -> green 127 passed | non terminée | Real H redirect behaviour not checked live |
| S2 | PARTIEL | DONE | #139 | `tests/test_human_questions.py` (all 17 audit phrases + homoglyphs/zero-width/spaced letters refused; benign steering incl. "08:00" allowed). Red: 22 failed -> green | non terminée | Text filter: not a complete injection boundary |
| S3 | PARTIEL | FAIT | #138 | `tests/test_auth.py`: rotating spoofed XFF, spoofed IP doesn't lock out another client, username backoff, bounded tables (5 red -> green) | non terminée | Uses the last XFF hop (Render proxy); if a second proxy is added, the key changes. Valid creds from a non-locked IP bypass the username backoff (avoids lockout DoS). |
| S4 | BESOIN HUMAIN | PARTIEL + BESOIN HUMAIN | #138 | `tests/test_infos_no_binaries.py` (only `.md/.txt` under `Infos/`, no tracked PDF anywhere). Green on the current tree, which no longer holds the PDFs, so it is a regression guard. | non terminée | Promo codes stay in git history. No history rewrite, no force-push. No gitleaks rule for the code pattern: gitleaks doesn't scan PDFs, and writing a pattern would mean reading the values. `.gitleaksignore` holds only the H docs sample key and one variable-name false positive. **HUMAN: revoke/regenerate the Linkup/Gladia/Stripe codes.** |
| S5 | PARTIEL | DONE | #139 | `tests/test_replay_export.py::test_s5_private_h_urls_are_not_exported` | non terminée | `share_url` (public H share link) kept on purpose |
| S6 | PARTIEL | DONE; FAIT | #139, #140 | `tests/test_framing_engine.py::test_s6_exact_address_never_reaches_llm_or_turns` (spy Holo client), `tests/test_redaction.py::test_s6_mask_address_*`; `tests/test_framing_holo.py`: spy Holo transport, address in first message / origin answer / free message, race name with "route/place" kept (4 red → green) | non terminée | Regex-based masking; unusual address formats may slip through; Address masking uses patterns (FR/EN street words, 5-digit postcodes); it does not detect every international address |
| S7 | PARTIEL | DONE | #139 | `tests/test_mission_store.py` (fakes: active restored steps get `cancel_session`, terminal steps don't, cancel errors swallowed). Red: 6 failed -> green | non terminée | Real effect on H quota not checked (fakes only) |
| S8 | PARTIEL | DONE | #139 | `tests/test_app.py`, `tests/test_h_lifecycle.py` (race name/URL/landmarks/preferences in delimited untrusted-data blocks, 200 chars, no newlines; `no_answer` retry keeps exactly one rules block). Red: 4 failed -> green | non terminée | Delimiting lowers but does not remove injection risk |
| S9 | PARTIEL | PARTIAL | #139 | `tests/test_app.py` (`share_url` no longer exposed as `live_view_url` nor in snapshot step data), `tests/test_capture_store.py` (24 h PNG purge on write + `purge()`). Red: 4 failed -> green | non terminée | Not done: skipping frame persistence for sensitive steps, per-user access control on `/steps/{kind}/screenshots/{n}.png` (deadline) |
| S10 | PARTIEL | FAIT (a, b, c) | #138 | voice tests: non-numeric `Content-Length` -> 400; WAV > 120 s -> 413 before the (fake) Gladia call; ffmpeg timeout + output caps; one non-queuing voice slot shared by `/api/transcribe` and the WebSocket ("voice busy"); WS foreign `Origin` refused; per-IP rate limit (last XFF hop) | non terminée | A missing `Origin` is still allowed (non-browser clients). Cross-site hijack not checked in a browser. |
| S11 | PARTIEL | FAIT | #138 | `tests/test_redaction.py`: each Basic password and each base64 pair masked, `hk-…`, URL userinfo, `token/access_token/api_key/key/secret` query values; numbered `HAI_API_KEY_N` still covered (6 red -> green) | non terminée | Pattern-based; new secret formats need new patterns. |
| S12 | PARTIEL | FAIT | #138 | workflow/render YAML tests, public health matrix, HSTS, `RUNAI_CSP_ENFORCE=1` (8 red -> green) | non terminée | smoke runs on `workflow_dispatch` only. `permissions: contents: read` on ci/smoke. deploy-health requires `event == 'push'` and probes `ok`/`version` only. `render.yaml`: `autoDeployTrigger: checksPass`, `numInstances: 1` kept. Public unauthenticated `/api/health` = `{ok, version}`; full details need valid Basic auth. HSTS in public mode only; `font-src 'self'`. CSP still report-only by default. Not tested against live GitHub or Render. |
| S13 | HORS PÉRIMÈTRE | HORS PÉRIMÈTRE | #138 | none | non terminée | `vocabulary_for()` is still called only by `gladia_vocabulary()`, its tests and the module itself, not by the app's voice flow. Left unwired and unchanged, as §S13 allows. |
| F1 | PARTIEL | FAIT (partial: no Linkup search on free choice text beyond the existing candidate search) | #140 | `tests/test_framing_engine.py` (15 red → green), `tests/redteam/test_framing_dead_ends.py` (now asserts that free text on a choice question is never copied into `race`) | non terminée | Clarification copy is English only |
| F2 | PARTIEL | PARTIEL | #140 | `tests/test_journey_planner.py` (23 red → green): all audit origins | non terminée | "Ask at most 2 times, then 'continue without origin'" not done (deadline) |
| F3 | PARTIEL | PARTIEL | #140 | `tests/test_framing_audit_w3.py`: nights/budget in words, no limit, TGV/Ryanair/covoiturage/Flixbus | non terminée | Clarifications in the user's language and front display of the server message not done (front is owned by someone else, app.js not touched) |
| F4 | PARTIEL | FAIT (backend) | #140 | `tests/test_framing_engine.py` (4 red → green): budget "800", nights "2.0"/"3", distance "10" | non terminée | Front `label(0)` for nights=0 not changed (app.js not touched) |
| F5 | PARTIEL | FAIT | #140 | `tests/test_framing_audit_w3.py`: the 6 audit sentences | non terminée | Heuristic list of stop words |
| F6 | PARTIEL | FAIT | #140 | `tests/test_framing_audit_w3.py`: $1,200 / 1,500 / 1 200 / 1.5k € / "my budget is 800" / "budget of 800" | non terminée | — |
| F7 | PARTIEL | PARTIEL | #140 | none | non terminée | Not started (deadline) |
| F8 | PARTIEL | PARTIEL | #140 | none | non terminée | Not started (deadline) |
| F9 | PARTIEL | FAIT | #140 | `tests/test_framing_audit_w3.py`: "train, not the plane", "pas en avion, en train", "not by car" | non terminée | — |
| F10 | PARTIEL | FAIT | #140 | `tests/test_framing_engine.py` (6 red → green): teleport, 999 nights, budget 0, 100000 km, 2019 date, readable correction turns | non terminée | The mocked Holo test now uses a future date (past dates are rejected) |
| F11 | PARTIEL | Not implemented | — | Not run | non terminée | W6 cancelled: structured controller not implemented. |
| F12 | PARTIEL | Not implemented | — | Not run | non terminée | W6 cancelled: framing persistence/reload recovery not implemented. |
| F13 | HORS PÉRIMÈTRE | Not implemented | — | Not run | non terminée | Coach parsing not covered by the six workstreams; no reproduction performed. |
| F14 | PARTIEL | PARTIEL | #140 | none | non terminée | Not started (deadline) |
| M1 | PARTIEL | DONE | #137 | `test_m1_user_id_round_trips_through_store_and_restart` (red: `stored["user_id"] is None`) | non terminée | none known |
| M2 | PARTIEL | DONE | #137 | `test_m2_cancel_on_terminal_mission_is_a_noop`, `test_m2_cancel_running_mission_leaves_no_active_step`; `test_mission_outcome.py::test_cancelling_after_completion_is_a_noop` replaces the test that encoded the old behaviour | non terminée | there is no `cancelled` step status (adding one would change contracts), so cancelled active steps become `failed` with `error="Cancelled by the user."`; the mission itself still reads `cancelled` |
| M3 | PARTIEL | DONE | #139 | `tests/test_human_questions.py::test_m3_*` ("08:00" to "...for your booking?" accepted; new attempt allowed after a refusal). Question context still checked for a bare "yes/oui" so S2 isn't weakened | non terminée | Medical-certificate eligibility questions not checked |
| M4 | PARTIEL | DONE | #137 | 4 × `test_m4_*` (red: wait without a deadline / `HCreditsExhausted` never raised / 3rd key never tried / block never expires) | non terminée | changed behaviour: the `quota_timeout_s` deadline now covers waiting for a **local** slot too, so a 2nd mission queued more than 300 s behind a full key fails with `HQuotaSaturated` instead of waiting forever |
| M5 | PARTIEL | DONE | #139 | `tests/test_h_runner.py::test_m5_unhashable_stop_screen_does_not_raise` (list/dict/int) ; `HRun.wait` failure handler no longer re-raises | non terminée | — |
| M6 | PARTIEL | DONE | #137 | `test_m6_closure_error_fails_the_mission_and_closes_the_stream` (red: mission stays `running`, SSE never closes) | non terminée | none known |
| M7 | PARTIEL | PARTIAL | #137 | — | non terminée | not done: removing `data.history` from `step` envelopes deletes key paths in the goldens `tests/contracts/golden/events_v1_keys.json` (rule 5: additive only, unless a deliberate separate commit), and the JSONL deltas / `asyncio.to_thread` were out of time. Growth stays quadratic |
| M8 | PARTIEL | DONE (partial for missions) | #137 | `test_m8_step_end_releases_capture_runs_and_dedup_state`, `test_m8_old_terminal_missions_are_pruned_from_memory` | non terminée | the M8 red test was not replayed separately (time); terminal missions leave memory after `RUNAI_MISSION_TTL_S` (default 24 h; files stay on disk); envelopes are still held whole in memory until then |
| M9 | PARTIEL | DONE | #137 | `test_m9_directory_fsync_is_posix_only_and_failures_are_explained` | non terminée | not run under real Windows (tested with `_POSIX=False` + `os.open` refusing directories) |
| J1 | PARTIEL | FAIT | #141 | `test_j1_geometry_requires_trusted_sourced_provenance` and `test_j1_agent_cannot_self_certify_geometry`: untrusted/H geometry previously verified → only official_api/human/linkup with URL can be verified; H flags ignored | non terminée | Provenance URL is evidence metadata, not independent route verification |
| J2 | PARTIEL | FAIT | #141 | `test_j2_ics_escapers_remove_every_line_break` and `test_j2_calendar_metadata_only_inserted_at_final_terminator`: CR/CRLF/LF injection and in-text terminator → escaped text, final calendar insertion only | non terminée | No external calendar-client import exercised |
| J3 | PARTIEL | FAIT | #141 | `partners.test.js`: inferred live badges, hardcoded Gladia and wrong lane matching → explicit provider + live mode; Demo/Recorded otherwise; `.step[data-kind]` matching | non terminée | DOM fixtures tested, not browser rendering |
| J4 | PARTIEL | FAIT | #141 | `test_j4_hotel_coverage_checked_without_checkin_times`: missing clock times suppressed hotel checks → date coverage and access durations preserved with unknown clocks | non terminée | Unknown hotel hours remain unknown (no fabricated appointments) |
| J5 | PARTIEL | FAIT | #141 | Six `test_j5_explore_english_only` cases; flyover and shell-map Node suites: French controls/fallback/errors → English, including ARIA announcements and parser errors | non terminée | Guard is scoped to owned Explore files, not every product string |
| J6 | PARTIEL | FAIT | #141 | `test_j6_return_using_assumed_pace_is_not_blocking`: assumed pace caused blocking return alert → warning explicitly says assumed 6:00/km; declared goal still blocks; shared contract updated | non terminée | Assumed time is still an estimate, clearly labelled |
| J7 | PARTIEL | FAIT | #141 | `test_j7_hotel_nights_use_selected_dates` (0/1/5) and race-eve regression: summary count diverged → stay-date count and mismatch/eve warnings | non terminée | Invalid/missing selection still requires user confirmation |
| J8 | PARTIEL | FAIT | #141 | `test_j8_integral_budget_is_formatted_without_decimal_suffix`, cents test and shell AC-56 test: €800 / €118.50, cap + known partial total retained; `test_budget_display` is now a normal passing test | non terminée | Other display paths are not claimed universally verified |
| J9 | PARTIEL | FAIT | #141 | Race-name and calendar UID insertion/revision regressions: mission-id title and positional/revision-dependent UID → optional `JourneyPlan.race_name`, source/type/time hash UID, `SEQUENCE=revision` | non terminée | Legacy stored plans without race name honestly show “Race to confirm”; changed event time yields a new UID as specified by audit |
| J10 | PARTIEL | PARTIEL; PARTIEL | #141, #136 | JURY-W1-1 unmasked and passing; JURY-W1-7 converted to strict xfail with PB-09 reference; Every e2e tracking xfail is now `strict=True`. JURY-W1-2/-3 were silent XPASS -> markers removed. JURY-W1-4 was hiding a `TypeError` (`summary=None`) -> null-safe, now passes, marker removed. AC-02 failed only because its French chip texts were no longer in `app.js` -> uses the current English chips and now fails on the real gap (`collecting` ≠ `ready_to_confirm`), still strict xfail. | non terminée | Race/hotel now agree; remaining assertion needs a sourced per-leg transport fare. Only step total is available, retained in budget without inventing a split. Other teams own framing/safety gaps; JURY-W1-1/5/6/7, GAP-W1-1, AC-02 and the 3 contract xfails remain strict xfails: the code fixes are in W3/W5 files (J4/J7/J8/J9, F*). |
| J11 | PARTIEL | PARTIEL; PARTIEL | #141, #136 | Updated NOTATION, backlog status/evidence, acceptance references and broken paths; AC-01/02/27/56/58 evidence tags added to owned tests; `tests/test_docs_state.py` (red: 3 failed -> green): NOTATION no longer says orchestrator/UX are "not coded" (`mission.py`, `voice_ws.py`, `live.html` exist); BACKLOG PB-01/PB-03 `done` (verified by grep), PB-04 `todo` (`tests/test_english_only.py` still absent); stale refs `test_framing_extraction_en.py` -> `test_framing_extract_english.py`, `static/styles.css` -> `style.css`. | non terminée | Complete 49-criterion mapping and whole-product English guard not completed within scoped deadline; docs explicitly distinguish implemented code, offline tests and unverified live/browser behavior; AC-xx tagging of tests (43/49 AC) not done: no time before the deadline. |
| J12 | PARTIEL | FAIT | #136 | `tests/test_tests_package.py`: a regular `tests` package appended to `sys.path` shadowed ours (red), passes after `tests/__init__.py`. Also: bare `from test_framing_engine import` -> `from tests.…`; contracts monkeypatch `GOLDEN` via the module object (the string `"contracts.…"` broke once `tests` became a package). | non terminée | Low |
| W6 | PARTIEL | Not implemented | — | Not run | non terminée | Controller cancelled for time; no implementation or tests. |

## Status counts

- PARTIEL: 46
- BESOIN HUMAIN: 1
- HORS PÉRIMÈTRE: 2

Total: 49 IDs. S4 requires human credential/promo-code revocation; no secrets were read or rotated. W6 was cancelled for time.
