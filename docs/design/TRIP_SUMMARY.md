# Your trip — terminal summary and shared RESULT CARD

Design handoff, Wave 1. Reference mockup: `mockups/trip-summary.html` (offline; fictional Demo data). This proposal changes no runtime UI or backend. All new contract requirements below are explicitly marked `NEEDED:`.

## Entry and hierarchy

Open **Your trip** once `mission.status` becomes `completed`, `failed`, or `cancelled`; these are the terminal values in `MissionStatusV2`. Do not navigate on `awaiting_human`, `searching`, or `running`. On transition, announce the terminal outcome once in a polite status region, then focus the heading without stealing focus from an active answer. Keep a route back to progress/history. Reloading a terminal mission opens this summary. Never restart automation from a summary link.

Desktop wireframe:

```text
RunAI                                      Demo · Your trip
YOUR TRIP
Ridgeway Trail
18 October 2026 · Bristol
[Prepared — nothing was booked or paid]
[Registration          ][Stay                  ][Transport             ]
[outcome · price       ][outcome · price        ][outcome · price       ]
[source URL + domain   ][source URL + domain    ][source URL + domain   ]
[collected time        ][collected time         ][collected time        ]
[confidence · mode     ][confidence · mode      ][confidence · mode     ]
[exact stop sentence   ][exact stop sentence    ][exact stop sentence   ]
[Finish on official ↗  ][Finish on official ↗   ][Finish on official ↗  ]
Known total / cap · assessment · missing lines
Export: HTML · PDF · ICS                 Open in Explorer →
```

Mobile wireframe (single column, DOM order unchanged):

```text
RunAI                 Demo
Your trip / race / date / city
Prepared safety banner
Registration RESULT CARD
Stay RESULT CARD
Transport RESULT CARD
Budget + missing lines
HTML · PDF · ICS
Open in Explorer →
```

## Shared RESULT CARD: one derivation, three surfaces

Use a single `deriveResultCard(snapshot, kind)` adapter for the live lanes, terminal summary, and Explorer lane panels. `mission.steps` is a **list**; `steps[kind]` means `steps.find(step => step.kind === kind)`, not array indexing. Registration → `registration`, Stay → `accommodation`, Transport → `transport`; omit the search step from these cards. Reuse the same rendered component, labels, money formatter, and state mapping, not separate per-surface fallbacks.

Single source = `mission.steps[kind]` + `mission.budget.lines`. Filter cost lines by matching `category`; include each matching line once, not step price plus line price. Step status owns outcome; journey geometry absence does not override it. Budget lines own budget arithmetic. If the step has no price → card says **Price unknown**, Explorer says the same string, even if cost-line estimates exist; show such estimates separately under “Budget estimate”, not as a verified step quote. Zero is a real price. With a step quote present, use `step.price_eur` (EUR); show any differing budget estimate separately and label the difference, never silently substitute it. Category sums are not evidence of a booked option. Mixed or contradictory evidence becomes “Details need review”, preserving both source values.

Apply SSE updates atomically using `mission.sequence`; never compose a new step with a cached old budget. Explorer must use the matching `mission.journey_revision`. If its journey fetch returns a different revision, keep the last consistent view and show “Updating trip details”; fetch the latest snapshot rather than inventing a reconciliation. This is an implementation requirement, not an existing adapter.

### Component states and exact outcome copy

| Step status / condition | Outcome | Stop and CTA behavior |
| --- | --- | --- |
| `stopped_before_commitment` | Prepared for your review | Show the actual stop point, never “Booked”; one primary official-site link if safe URL exists. |
| `completed` | Research complete | No booking inference; show stop only if supplied. |
| `failed` | Could not prepare this option | Retain sourced facts and price if present; show safe error detail, not a blank card. |
| `pending` | Not started | At terminal cancellation: “Not prepared before cancellation”. |
| `running` | In progress | At a terminal mission: “Preparation ended before a result was available”. |
| `paused` / `waiting_for_user` | Needs your input | At terminal state retain this outcome as “Unfinished — needs your input”; do not reopen expired questions. |
| Missing step | No result available | All unknown fields explicit; no invented stop or CTA URL. |
| Missing price / source / time | Price unknown / Source unavailable / Collection time unknown | Never hide the card or turn missing money into zero. |

Exactly **one primary CTA per result card**: “Finish on the official site” with an external-link icon. Its accessible name is “Finish on the official site for Registration (opens in a new tab)” (substitute Stay or Transport). UX-07, `tests/ux_acceptance/README.md:16`, requires a new tab to be announced in the link name; this is the English equivalent of that existing criterion. Use `target="_blank" rel="noopener noreferrer"`; hide the decorative icon from accessibility APIs. Show source links as secondary text, also announcing a new tab. Allow only http(s), reject credentials and unsafe schemes. Do not expose signed session URLs, user details, or an H cloud live-view URL as a finish link. If no trustworthy official destination exists, render “Official link unavailable” as text rather than a dead or speculative button. External navigation transfers control to the runner; RunAI never submits, pays, or enters card details.

## Field mapping and evidence gaps

All paths below are API JSON paths unless qualified as JourneyPlan. `step` is the selected list entry; `line` is a matching budget line. Arbitrary `step.data` is not a guaranteed typed contract.

| Visible field | Existing field path or required addition | Fallback / rule |
| --- | --- | --- |
| Hero race / city / date | `mission.race.name`, `.city`, `.race_date` | Race not identified / City unknown / Date unknown. |
| Terminal outcome / mode badge | `mission.status`, `mission.mode` | Live / Demo / Replay; mode is independent of confidence. |
| Card title / outcome / description | `step.kind`, `.status`, `.summary`, `.error` | Use state table; summaries are untrusted text, never HTML. |
| Card price | `step.price_eur` | EUR only; null → Price unknown. |
| Budget estimate and currency | `mission.budget.lines[].money.amount`, `.currency` | Filter by `line.category`; all same currency enforced by Budget. |
| Source URL + domain | `step.url`; `line.money.provenance.url` for budget estimate | Display full URL with wrapping and hostname parsed by URL; never a made-up source. |
| Quote collection time | `line.money.collected_at`, `.provenance.collected_at` | These currently may reflect mission creation time (see projection), not observation time. **NEEDED:** `StepResult.collected_at: datetime | null` for actual step quote collection. Until populated, label budget timestamps “Budget evidence recorded”; card says Collection time unknown. |
| Quote confidence | `line.money.confidence` for budget evidence only | **NEEDED:** `StepResult.confidence: Confidence` default unknown for step evidence. Do not transfer a line's confidence to an unrelated step quote. |
| Provenance label / provider | `line.money.provenance.kind`, `.label` for budget evidence | **NEEDED:** `StepResult.provenance: Provenance | null` for step result attribution (H agent, Linkup, official API, etc.). |
| Exact stop | `step.stop_point` + `step.url` | Enum identifies category, not exact screen or domain verification. **NEEDED:** `StepResult.stop_evidence: {screen_label: str, url: HttpUrl, observed_at: datetime, card_details_entered: bool | null} | null`. |
| Official CTA | `step.url`; registration fallback `mission.race.registration_url`; relevant `mission.limitations[].manual_url` with `.step` matching kind | These URLs exist but official status is not typed. **NEEDED:** `StepResult.official_url: HttpUrl | null`, validated by backend source policy; do not assume arbitrary reached URLs are official. |
| Total / cap / missing costs | `mission.budget.known_total`, `.currency`, `.cap`, `.over_cap`, `.complete`, `.missing_line_ids`, `.lines[].id`, `.category`, `.money` | No budget → Budget unavailable; never claim a zero total when no evidence exists. |
| Export revision / ID | `mission.journey_revision`, `mission.mission_id` | Hide active export links when revision null, explain “Exports available when trip details are ready”. |
| Explorer / route / duration / time zone | JourneyPlan `.revision`, `.stops[].coords`, `.segments[].duration_min`, `.departure`, `.arrival`, `.timezone`; JourneyPlan `.timezone` | No geometry or time inference from a step summary. |

Confidence labels: `verified` → Verified, `estimated` → Estimated, `unknown` → Unknown, `illustrative` → Unknown with “Illustrative only” detail. Illustrative is never upgraded to Estimated or Verified. A Demo / Replay badge remains visible beside any confidence label, including Verified; verified fixture data is not live evidence. The mockup supplies proposed evidence fields as fictional illustrative design fixtures, not claims about present API completeness.

### Stop-point language

Use `stop_point` to select wording: payment → “Stopped before payment”; consent → “Stopped before accepting terms”; health_declaration → “Stopped before a health declaration”; account_creation → “Stopped before creating an account”; submission → “Stopped before final submission”. Add “on {domain}” only with a valid observed URL. Null → “Stop point not recorded”. Do not copy current French `human_action` strings: the v2 StepResult contract does not contain `human_action`.

Only with observed payment screen evidence and `card_details_entered === false`, use: **“Stopped on the payment page of njuko.com — card details were never entered.”** Otherwise retain the shorter category sentence; do not manufacture the negative assertion from a keyword detector. `runai/safety.py:53` detects text patterns, not audited UI actions. Other exact screen labels follow the same evidence requirement. Terminal completion means preparation ended, not that the runner owns an entry, room, or ticket.

## Budget and formatting

Show “Known total €800 / cap €900”. All known lines (including local/other charges) contribute once, missing prices never count as zero. Use server totals; do not add card quotes again. List every missing line, e.g. “Transport: price unknown”, mapped by missing ID to line category/label. If no matching ID exists show “Unspecified cost: price unknown”.

Assessment: cap null → **Cap not given**; `over_cap === true` → **Over cap**; `over_cap === false` and complete → **Within cap**. When cap exists and total is incomplete and not already over cap, say **Known total within cap — final total unknown**, not unconditional Within cap. Missing budget → “Budget unavailable”. These are distinct from an unassessable cap.

Money must use `Intl.NumberFormat("en", {style: "currency", currency, minimumFractionDigits: Number.isInteger(amount) ? 0 : 2, maximumFractionDigits: Number.isInteger(amount) ? 0 : 2})`: EUR €800 or €82.50, never raw float strings. Step quotes default to EUR because the existing field is explicitly `price_eur`; budget uses its declared currency. Reject non-finite values; null is not zero. Never perform silent currency conversion. Keep symbol and amount together.

Dates: English `Intl.DateTimeFormat("en", {day:"numeric", month:"long", year:"numeric"})`; treat `race_date` as a calendar date, not midnight UTC converted into another day. Collection time: “collected 3 min ago · 21:42”, with `<time datetime="ISO">` and a title/accessible description containing full date, zone, and offset. Use a 24-hour clock, explicit trip zone from JourneyPlan (otherwise label device zone), English relative units: just now, 1 min ago, 3 min ago, 2 h ago, 1 day ago. Replay time is relative to original recording, never freshness now; label “Recorded … · Replay”. Future/skewed timestamps show absolute time plus “Clock needs review”; missing timestamps show Collection time unknown. Refresh relative labels once per minute without repeated live announcements. Dates older than a day also show the date visibly.

Durations: `duration_min` → “2 h 15 min”, 60 → “1 h”, 0 → “0 min”; null → “Duration unknown”. Missing departure/arrival → “Time not provided”, not a duration estimate; append zone for real times. Never infer a train schedule or check-in from the race date.

## Copy table and terminal variants

| Context | English copy |
| --- | --- |
| Complete hero | Your trip / Prepared — nothing was booked or paid |
| One lane failed | Partially prepared — nothing was booked or paid / Transport needs your attention |
| Mission failed | Preparation stopped — nothing was booked or paid / Some results may still be useful |
| Cancelled | Preparation cancelled — nothing was booked or paid / Results collected before cancellation are kept below |
| No results or race | No trip prepared yet / No result available / Race not identified |
| No price (all surfaces) | Price unknown |
| No schedule | Time not provided |
| No official link | Official link unavailable |
| Export failure | Export unavailable. Try again. Your trip has not changed. |
| Secondary navigation | Open in Explorer |

Keep all three cards in partial, failed, and cancelled states; preserve useful evidence, show safe redacted errors, never replace an entire mission with a success banner. If completed but some lane failed, use the partial banner. No confetti, paid/confirmed icons, “Booking confirmed”, or auto-redirect. Unknown hero facts remain explicit. Terminal pages have no “Cancel preparations” button.

## Exports and Explorer

Export row: HTML / PDF / ICS → `/api/missions/{id}/recap.{format}?revision={journey_revision}`, URL-encode mission ID and pin all three to the same revision as shown (`runai/app/server.py:228–255`). HTML preview opens a new tab with that fact in its link name; PDF and ICS retain format in accessible names, without falsely promising a download (current response is inline). A 404/503 is an inline export error, not a replacement trip; allow retry. Existing export renderers are not automatically English or card-consistent: implementation must reuse the shared derivation / equivalent server projection, not assume this docs change fixes `runai/recap/build.py`, `render.py`, or templates.

“Open in Explorer” is secondary internal navigation for the same mission/revision, not another primary CTA. Keep text lane panels even if map unavailable. Initial map frames relevant valid race/hotel geometry; for long travel use chapter fit, never default whole-world as the primary experience. If no coordinates exist, hide the map and say “Map unavailable — trip details are shown below”; do not create coordinates from labels.

## Contradiction checklist (jury regression acceptance)

1. **Hotel not chosen**: current equivalent `runai/journey/planner.py:421–423` is “Hôtel non choisi” when structured hotel place is absent. A completed accommodation step with price/URL but no geometry stays “Research complete” or “Prepared for your review” on every card; only map location says Location unknown. Do not claim a missing selection from missing coordinates.
2. **Train not found**: current equivalent `runai/journey/planner.py:439–446` constructs a missing-transport warning when structured outbound is absent. Derive lane outcome from the transport step, distinguish “Route details unavailable” from a failed search; never override a prepared step with a generic planner warning.
3. **“Horaire non renseigné”**: `web/flyover/journey-fallback.js:110–111`. Replace with Time not provided using the shared English formatter. Known step result and unknown timetable can coexist without contradiction.
4. **World-zoom map**: `runai/app/static/journey-view.js:36–42` creates the map without initial center/zoom; `web/flyover/journey-player.js:95–104` skips framing without bounds. This is a reachable risk, not a reproduced production cause. Fit relevant sourced geometry or show the text fallback before exposing the map; no world-view success state.
5. **“800.0”**: jury-reported raw-float symptom; literal not found in the inspected runtime files. `web/flyover/journey-fallback.js:33–37` has a raw amount fallback; `runai/app/static/shell-core.js:23–28` uses a French money formatter; recap money rendering lives in `runai/recap/render.py:45–46` and `templates/recap.html.j2:105`. Use the shared English Intl formatter above (equivalent server formatting for exports), with integer fraction digits suppressed. Do not claim the literal's production origin was verified.

## Implementation acceptance

- Full, empty, failed-lane, cancelled, null-budget, zero-price, incomplete-cap, illustrative, Demo and Replay fixtures use identical result text in all surfaces at one revision.
- Check €800 and €82.50; no raw floats; missing step price yields exactly Price unknown in summary, live lane and Explorer even if budget has an estimate.
- Payment sentence only appears with explicit screen/card-entry evidence; absent evidence never asserts an exact payment page.
- One primary official CTA per card when destination is trustworthy; keyboard focus visible, external-link name announces new tab, no navigation happens automatically.
- Export revision retained on retry; unknown coordinates do not expose a world map; at 390px cards stack with no horizontal scroll.
- Backend additions and frontend runtime changes are follow-up work, not shipped by this reference mockup. Any static implementation requires its own `front-night` PR for morning review.
