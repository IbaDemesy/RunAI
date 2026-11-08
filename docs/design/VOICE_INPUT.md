# Voice input & live transcript — component spec (Gladia showcase)

Status: design spec for wave 1. Mockup: [`mockups/voice.html`](mockups/voice.html) (offline, open it in a browser and press **Play demo stream**).

Today the mic button records, POSTs to `/api/transcribe` and only returns final text, so Gladia is invisible. This spec defines the UI that the streaming pipeline (partials, code-switching, translation, NER, voice commands) lands in. It reuses the state names of `web/voice/voice-input.js` and the dark tokens already in `runai/app/static/styles.css` (`--night`, `--haze`, `--sun`, `--chalk`, `--mist`).

## 1. Principles

1. **Show Gladia working, never fake certainty.** Partials are visibly provisional; NER only proposes, the runner confirms.
2. **Revise in place.** One line per utterance, keyed by Gladia `data.id`. A newer partial or the final replaces the provisional text of the same id; revisions are never appended.
3. **Text always works.** Any failure (unsupported, permission denied, error) falls back to the text field with focus moved there.
4. **Quiet for assistive tech.** `aria-live="polite"` announces finals only; partials are `aria-hidden`.

## 2. Mic button states

State names are exactly those emitted by `createVoiceInput().onStateChange` (`snapshot.state`).

| State | Button label / icon | Visual | Badge "Powered by Gladia solaria-1" | Live transcript line | Text fallback | Screen reader |
| --- | --- | --- | --- | --- | --- | --- |
| `idle` | "Speak" · mic | Outline button, `--haze` border | Hidden | Hidden (or last final, dimmed) | Enabled | `aria-pressed="false"` |
| `requesting_permission` | "Allow microphone…" · mic + spinner | Button disabled, hint "Your browser is asking for microphone access" | Hidden | Hidden | Enabled | Polite: "Waiting for microphone permission." |
| `permission_denied` | "Microphone blocked" · mic-off | `--sun` warning text: "Microphone access was denied. Type your request instead." + "How to enable" link | Hidden | Hidden | **Focused** | Polite: the warning text |
| `unsupported` | "Voice unavailable" · mic-off | Button disabled, hint "This browser cannot record audio. Type instead." | Hidden | Hidden | **Focused** | Polite: the hint |
| `listening` | "Stop" · square | Filled `--sun` button + 5-bar level meter + elapsed timer | **Visible** | Partials in `--mist`, finals in `--chalk` | Enabled (typing stops nothing) | `aria-pressed="true"`; polite: "Listening." once |
| `transcribing` | "Finishing…" · spinner | Button disabled, meter frozen at 0 | **Visible** | Last partial pulses until the final arrives | Enabled | Polite: "Transcribing." |
| `error` | "Try again" · mic | `--sun` error line with readable message (from `snapshot.message`) | Hidden | Kept (what was heard stays visible) | **Focused** | Polite: the error message |

Keyboard: the mic is a real `<button>`; `Space`/`Enter` toggles start/stop; `Esc` while `listening` stops recording; focus never leaves the button while it changes label. `Alt+M` is an optional global shortcut (documented in the button `title`).

### Level meter

- 5 vertical bars driven by an `AnalyserNode` RMS value (0–1), updated at most every 80 ms.
- **Reduced motion** (`prefers-reduced-motion: reduce`): bars are replaced by a single static dot whose opacity steps between 3 levels (no movement, no scaling), plus the text "Listening" — the mockup has a toggle to preview it.

## 3. Live transcript line

Placed directly under the ask field, in a container with `aria-live="off"` (not `role="log"`, which is implicitly live and would double-announce finals and translations); announcements go only through the dedicated polite region.

- Each utterance is one `<p data-utterance-id="{data.id}">`.
- Partial (`is_final=false`): text in `--mist`, italic, trailing caret; `aria-hidden="true"`.
- Final (`is_final=true`): text in `--chalk`, normal weight; the node is copied into a visually hidden `aria-live="polite"` region so only finals are read.
- When a message arrives for an existing id, **replace** that node's text; never append a second node.
- Language label at the start of the line (`FR`, `EN`, `PT`), from `utterance.language`. When the language differs from the previous utterance, the label flashes `--sun` once and a small "Language switched to Portuguese" chip appears for 3 s (**code-switching indicator**). Text labels, not flags only (flags are not languages).
- **Translation**: when the source language is not English, a second line under the original, prefixed "→ EN", in `--haze`, smaller type. It appears when the translation message for that utterance id arrives; until then nothing is shown (no placeholder churn).

## 4. NER → "understood" chips as candidates

The existing `ul.understood` chips (see `understood()` in `app.js`) gain a **candidate** variant:

- An entity whose type maps to a slot (`race`, `city`, `date`, `budget`, `distance`) lights the matching chip with a dashed `--sun` outline and the value followed by "?" — e.g. `Lisbon Half Marathon ?`.
- The entity text is also underlined (dotted `--sun`) inside the final transcript line, linked by `aria-describedby` to its chip.
- Clicking/Enter on the chip opens an inline "Is this right?" with **Yes** / **Edit**. Yes posts the slot as a framing reply (same path as text); Edit focuses the text field prefilled.
- Candidates are **never authoritative**: they are not sent to H, and Holo's extraction still wins. A candidate disappears if Holo's slot for that field becomes `answered` with a different value.

Mapping (Gladia NER labels are alpha and may vary; map in the backend):

| Gladia entity type (examples) | Slot chip |
| --- | --- |
| `event`, `organization` containing a race keyword | race |
| `location`, `city`, `gpe` | city / origin |
| `date`, `time` | date |
| `money` | budget |
| `quantity` with km / "10K" / "half" | distance_km |

## 5. Mid-mission voice commands

Commands come from `runai/voice/commands.py` (`CommandKind`: `pause`, `resume`, `correction`, `cancel`, `new_mission`). Example phrases: "pause", "stop", "switch to 10K".

Two-step indicator, as a pill above the live mission view:

1. **Requested** — `●` hollow, `--mist`: "Pause requested (voice)". Shown as soon as the command is parsed, including `early=true` commands from partials.
2. **Confirmed by H** — `●` filled, `--ok`-green on dark: "Paused · confirmed by H" once the H session status reaches the target (`paused`, `running`, …) or the correction is acknowledged by the orchestrator.
3. **Failed** — `--sun`: "H did not confirm the pause. Retry" with a retry button, after a 10 s timeout.

The pill is announced politely at step 1 and step 2 only. Destructive commands (`cancel`) require an on-screen "Cancel mission?" confirmation before being sent.

## 6. Event → UI mapping

Gladia live (`solaria-1`) message names as received by the backend, and what the browser does with the relayed event.

| Gladia WS message | Condition | UI effect |
| --- | --- | --- |
| `transcript` | `data.is_final=false` (partial) | Upsert line `data.id` in `--mist`; language label from `data.utterance.language`; never announced |
| `transcript` | `data.is_final=true` (final) | Replace line `data.id` text in `--chalk`; announce once; route to framing/commands |
| `transcript` | language differs from previous final | Code-switching chip "Language switched to …" |
| translation (`translated_utterance` payload) | target `en`, source ≠ `en` | Add/replace "→ EN" line under utterance `utterance_id` |
| `named_entity_recognition` | entity maps to a slot | Candidate chip + dotted underline in the final line |
| (RunAI) `command` event | `early=true` or final | Command pill → **Requested** |
| (RunAI) mission/H status event | status matches command | Command pill → **Confirmed by H** |
| WS close / error | any | State `error` with readable message; keep transcript; focus text field |

## 7. NEEDED from backend (WS → browser event shape)

One stream (SSE or WS) of JSON events, each with `type`, `at`, `session_id`:

1. `voice.transcript` — `{utterance_id, text, is_final, language, start, end, confidence}` (already `TranscriptEvent`; keep `utterance_id` = Gladia `data.id`).
2. `voice.translation` — `{utterance_id, source_language, target_language: "en", text}`.
3. `voice.entities` — `{utterance_id, entities: [{text, gladia_type, slot | null, value, start, end}]}`; `slot` mapped server-side using the table in §4.
4. `voice.level` — optional `{rms: 0..1}` at ≤ 12 Hz only if the meter cannot use a local `AnalyserNode` (preferred: local).
5. `voice.command` — existing `CommandEvent` plus a `command_id`.
6. `voice.command_ack` — `{command_id, status: "confirmed" | "failed", by: "h" | "orchestrator", detail}`.
7. `voice.session` — `{state: "listening" | "transcribing" | "closed" | "error", model: "solaria-1", languages: ["fr","en","pt"], message}` so the badge and error text come from the server.
8. A `POST /api/voice/candidates/{utterance_id}` (or reuse the framing reply) to confirm an NER candidate with `{slot, value}`.

## 8. Acceptance checklist

- [ ] Every state in §2 is reachable in the mockup (state switcher).
- [ ] Partials replace in place by `data.id`; no duplicate lines after the scripted stream.
- [ ] Only finals and command pill steps are announced.
- [ ] Badge visible only in `listening` / `transcribing`.
- [ ] Reduced-motion variant has no animated movement.
- [ ] English only; the mockup makes no network request.
