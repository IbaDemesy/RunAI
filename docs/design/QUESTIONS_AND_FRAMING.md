# Framing & human-question flow — fix spec (U4)

Status: spec for one `front-night` PR (Frontend team) plus small backend/prompt follow-ups.
Scope: the framing screen (`renderStart`, `renderFraming`) and mission question cards (`questionBlock`).
Source of truth for "before": `origin/main` at `3373e01`. Line numbers refer to that commit.
Nothing under `runai/app/static/` is changed by this document.

Referenced IDs:

- **UX-01 — focus never jumps.** After any mutation the focus stays on the control the user acted on,
  or moves to the next logical control in the *same* card; it never falls back to the page `h1`
  while the user is answering. Today `render()` rebuilds the whole screen and, when the focus key is
  gone, focuses the `h1` (`app.js:121-129`).
- **UX-04 — one status region.** `#feedback` (`index.html:34`, `role="status"`, `aria-live="polite"`)
  is the only place transient status is announced; one short sentence; errors switch it to
  `role="alert"` styling (`className = "error"`), never both regions at once.

Owners: **FE** = Frontend (`runai/app/static/*`, front-night PR), **BE** = Backend/orchestration,
**HOLO** = Prompt engineering / Holo, **DATA** = demo fixtures.

---

## 0. Wireframes

### 0.1 Framing screen — state `asking` (`framing.status = collecting`, one open question without candidates)

```
┌──────────────────────────────────────────────────────────────┐
│ RunAI                                         [ Demo mode ]  │
├──────────────────────────────────────────────────────────────┤
│ What I understood                                            │
│ (✓ Marathon · 42.2 km) (✓ From Lyon) (◔ Period?) (○ Budget)  │
│                                                              │
│ Holo: Which month or season suits you? Say "any" if you are  │
│       flexible.                                              │
│                                                              │
│ [ Spring ] [ Autumn ] [ Any time ]           ← choice chips  │
│                                                              │
│ ┌──────────────────────────────────────────────┐ [ Send ]    │
│ │ Type or speak your answer…                   │ [ 🎤 Speak ]│
│ └──────────────────────────────────────────────┘             │
│ ▸ Edit something                                             │
│                                          [ Cancel request ]  │
└──────────────────────────────────────────────────────────────┘
#feedback (status): ""   — empty while idle
```

### 0.2 Framing screen — state `candidates` (`choosing_candidate`)

```
┌──────────────────────────────────────────────────────────────┐
│ What I understood                                            │
│ (✓ Milan) (✓ Marathon · 42.2 km) (✓ April 2027) (✓ From Lyon)│
│                                                              │
│ Holo: I found 1 race that matches. Check it below and choose │
│       it, or tell me if it is not the right one.             │
│                                                              │
│ ┌────────────────────────────────────────────┐               │
│ │ Milano Marathon (demo)                     │               │
│ │ Milan · IT · 2027-04-11 · 42.195 km        │               │
│ │ Demo data · recorded event, not live       │               │
│ │ Official source ↗            [ Choose ]    │ ← aria-label  │
│ └────────────────────────────────────────────┘   "Choose     │
│ [ None of these — I'll specify ]                 Milano      │
│                                                  Marathon"   │
│ ┌──────────────────────────────────────────────┐ [ Send ]    │
│ │ Or type the official name or URL…            │             │
│ └──────────────────────────────────────────────┘             │
│                                          [ Cancel request ]  │
└──────────────────────────────────────────────────────────────┘
```

### 0.3 Framing screen — state `ready_to_confirm`

```
┌──────────────────────────────────────────────────────────────┐
│ What I understood                                            │
│ (✓ Milano Marathon) (✓ 11 Apr 2027) (✓ 42.2 km) (✓ From Lyon)│
│ (✓ 2 nights) (✓ Train) (— No budget cap)                     │
│                                                              │
│ ┌─ Ready to launch ────────────────────────────────────────┐ │
│ │ Milano Marathon (demo)                                   │ │
│ │ • Milan · Sun 11 Apr 2027 · 42.195 km                    │ │
│ │ • From Lyon · 2 nights (10–12 Apr) · train               │ │
│ │ • Budget: no cap                                         │ │
│ │ ⚠ limitations, if any (one line each, with link)         │ │
│ │                                                          │ │
│ │ Three agents will browse for you: registration, hotel    │ │
│ │ and transport. They stop before any payment.             │ │
│ │                                                          │ │
│ │ [ Launch the agents ]      ▸ Edit something              │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────┐ [ Send ]    │
│ │ Anything to add? Type it here…               │             │
│ └──────────────────────────────────────────────┘             │
│                                          [ Cancel request ]  │
└──────────────────────────────────────────────────────────────┘
```

### 0.4 Mission question card — five states

All five share the same box, same position and same height budget; only the body changes.
The card is keyed by `question_id` (`data-question-id`) so a re-render reuses the node in place.

```
OPEN                                   SENDING (after click on "3h30–4h")
┌ Registration · Your answer needed ┐  ┌ Registration · Sending… ──────────┐
│ What finish time are you aiming   │  │ What finish time are you aiming   │
│ for? It sets your start pen.      │  │ for? It sets your start pen.      │
│ [ Under 3h30 ] [ 3h30–4h ]        │  │ [ Under 3h30 ] [■3h30–4h■]        │
│ [ Over 4h ]                       │  │ [ Over 4h ]     (all disabled,    │
│ ┌───────────────────────┐[ Send ] │  │                  chosen pressed)  │
│ │ Or type an answer…    │         │  │ ┌───────────────────────┐[Send] │
│ └───────────────────────┘         │  │ └───────────────────────┘ (dis.)│
└───────────────────────────────────┘  └───────────────────────────────────┘

ANSWERED (same place until next full render)   EXPIRED
┌ Registration · ✓ Answered ────────┐  ┌ Registration · Expired ───────────┐
│ What finish time are you aiming   │  │ What finish time are you aiming   │
│ for? It sets your start pen.      │  │ for? It sets your start pen.      │
│ Your answer: 3h30–4h              │  │ The agent moved on without an     │
│ (buttons removed, no input)       │  │ answer. Nothing was submitted.    │
└───────────────────────────────────┘  └───────────────────────────────────┘

REFUSED
┌ Registration · ✕ Not accepted ────┐
│ What finish time are you aiming   │
│ for? It sets your start pen.      │
│ Your answer: "sub 2h" was not     │
│ accepted: <question.reason>.      │
│ The agent will ask again if needed│
└───────────────────────────────────┘
```

---

## 1. The 10 fixes (before / after / acceptance)

### 1. Mission question cards must not move or collapse when answered (FE)

| | |
|---|---|
| **Before** | `renderMission()` puts open questions in a priority section at the **top** (`app.js:482-485`, heading "À vous de répondre") and non-open ones **at the bottom** after the steps (`app.js:517`). Answering triggers `mutate()` → `render()` → `screen.replaceChildren()` (`app.js:112`), and the SSE `question_resolved` refresh also calls `render()` (`app.js:372, 376`). The answered card therefore disappears from under the pointer and the next card (or the steps list) slides up into its place. Juror 3 clicked "moins de 3h30" on the second card because the first collapsed between mousedown and click. Focus then falls back to the `h1` (`app.js:127-128`), breaking UX-01. |
| **After** | 1. On click of a choice: immediately (before the request) set the card to **sending**: all its buttons `disabled`, chosen button `aria-pressed="true"`, header text "Sending…". Other cards are untouched. 2. On success: switch the same DOM node to **answered** ("✓ Answered", "Your answer: <answer>"), remove buttons and input. 3. Keep this node **in the open section, at the same index**, for the rest of this render cycle and for SSE refreshes; it is moved to an "Answered" `<details>` section (collapsed, after the steps) only on the next *full* render that is not caused by this answer (navigation, reload, or a later answer's success). Implementation: keep a `settling` `Set<question_id>`; `renderMission` renders questions in `settling` inside the open section in their previous order, and clears the set at the start of the next user-initiated mutation. 4. A newly opened question is **appended** to the end of the open section, never inserted above an existing card. 5. Focus (UX-01): after success, move focus to the first enabled control of the **next open card** if one exists; otherwise to the card's own heading (`tabindex="-1"`). Never to the page `h1`. On error: re-enable the card, keep the chosen value in the input, focus the chosen button, announce the error (item 10). 6. On 409 (`revision` stale): reload, keep the card where it was, show "This question changed. Check it and answer again." inside the card. |
| **Acceptance** | (a) With two open questions, clicking any choice in card 1 does not change the bounding box (`top`, `height`) of card 1 or card 2 until the next unrelated render — static test: after answer, `.agent-question[data-question-id=q1]` is still the first child of `.questions`. (b) A second click on card 1 during sending is a no-op (buttons disabled). (c) After success, `document.activeElement` is inside card 2 (or card 1's heading if it was the last). (d) No `h1` focus during the answer flow. (e) The "Answered" section exists only when ≥1 settled non-open question, collapsed by default. |

### 2. Honest button labels (FE)

| | |
|---|---|
| **Before** | Mission question free-text submit: `form(block, "Votre réponse · " + question.text, …)` (`app.js:391`) → `button("Envoyer · " + title)` (`app.js:82`), so the visible button reads **"Envoyer · Votre réponse · Quel temps visez-vous ? (pour le sas de départ)"**. Focus keys use `"button:" + textContent` (`app.js:119`), so long labels also collide. Framing dock: `aria-label` "Envoyer · Votre réponse · <whole question>" (`app.js:172, 347`). Candidate cards: visible **"Choisir cette course · <name>"** (`app.js:303`). Slot editor: "Corriger · <label>" (`app.js:321`) and inner submit "Envoyer · Nouvelle valeur : <label>" (`app.js:323` → `:82`). |
| **After** | • Choice buttons: visible text = **choice text only** (`Under 3h30`), no prefix; accessible name = same. • Free-text submit: visible **"Send"**; the input gets a visible-or-sr-only `<label>` "Your answer"; both input and submit get `aria-describedby` → id of the card's question heading (`q-<question_id>-text`). Never concatenate the question into a button name. • Framing dock submit: visible "Send", `aria-describedby` → the `say` paragraph id; no `aria-label`. • Candidate button: visible **"Choose"**, `aria-label="Choose <race name>"`. • "None of these — I'll specify" stays as a choice button. • Slot editor: visible "Edit", `aria-label="Edit <slot label>"`; inner submit "Save", `aria-label="Save <slot label>"`. • Focus keys use a stable id (`data-focus-key="q:<id>:choice:<index>"`, `"q:<id>:send"`, `"cand:<id>"`), not the button text. |
| **Acceptance** | (a) No button `textContent` longer than 40 chars on framing or mission screens with fixtures `framing_vague`, `framing_candidates`, `framing_ready`, `mission_snapshot`. (b) No button text contains "·". (c) Every "Send" has `aria-describedby` pointing to an existing element whose text is the question. (d) Each candidate "Choose" button has a unique accessible name. |

### 3. Empty "User answers: ." (BE)

| | |
|---|---|
| **Before** | `fakes.py:247` always appends `f" Réponses utilisateur : {' ; '.join(answers)}."`; the accommodation lane has no questions (`fakes.py:162`), so its summary ends with **"Réponses utilisateur : ."** (rendered as "User answers: ." once translated) in the step card (`app.js:407`). |
| **After** | Append the sentence only when `answers` is non-empty: `if answers: summary += f" Your answers: {'; '.join(answers)}."`. Same guard for `self._messages` (already guarded, `fakes.py:248`). Apply the same rule in any real/replay summary builder: never render a label followed by an empty value. FE rule (defensive, same PR as items 1–2): when a step exposes structured `data.user_answers`, render a "Your answers" line only if the list is non-empty. |
| **Acceptance** | Unit test: run `FakeAgentRun` for `StepKind.accommodation` → `result.summary` does not contain "answers" and does not end with ": .". Registration summary contains "Your answers: " followed by non-empty text. |

### 4. Duplicated start-pen question → one question per purpose (BE / DATA)

| | |
|---|---|
| **Before** | `fakes.py:151-161` registration asks two questions for the same purpose: "Quel sas souhaitez-vous examiner (démo) ?" [Découverte, Performance] **then** "Quel temps visez-vous ? (pour le sas de départ)" [moins de 3h30, 3h30–4h, plus de 4h]. Both pick a start pen; they open back-to-back, which caused item 1's mis-click. |
| **After** | One question per purpose, at most one open per lane at a time (questions are asked sequentially — the next one opens only after the previous is resolved, which `_run` already does with `await`). Allowed questions per lane, in order: |

| Lane | # | Purpose | Question (English) | Choices | Free text |
|---|---|---|---|---|---|
| registration | 1 | Start pen | "What finish time are you aiming for? It sets your start pen." | `Under 3h30`, `3h30–4h`, `Over 4h`, `First marathon / no target` | yes |
| registration | 2 (only if the form has it) | Race T-shirt size | "Which T-shirt size should I select?" | `XS`, `S`, `M`, `L`, `XL` | no |
| accommodation | — | none in demo | — | — | — |
| accommodation (live, optional) | 1 | Ambiguous hotel choice | "Two hotels fit your budget near the start. Which one should I keep?" | the two hotel names | no |
| transport | 1 | Departure time | "When would you like to leave the day before the race?" | `Morning`, `Afternoon`, `Evening` | no |

Rules: a lane never asks for data already in the framing summary (origin, dates, nights, budget, transport mode); a lane never asks two questions that set the same form field; the demo set is registration#1 and transport#1 only.

| | |
|---|---|
| **Acceptance** | `QUESTIONS[StepKind.registration]` has exactly 1 entry in demo; the `mission_snapshot` contract fixture has no two questions with the same `step` and the same purpose; no question text contains "(démo)"/"(demo)". |

### 5. "Understood" slot chips with explicit states (FE + BE)

| | |
|---|---|
| **Before** | `understood()` (`app.js:253-261`) shows a filled chip for `answered`/`sourced`, a "<label> ?" `chip empty` for anything else (max 3), hides `not_needed`. `asked` and `unknown` look identical; sourced vs answered is invisible. "Période ?" stays visible after a candidate is chosen because `race_date` becomes `sourced` (`engine.py:241-261`) while `date_window` stays `unknown` — the chip should be replaced by the date. After re-framing (`discovery_changed`, `engine.py:192-199`) the backend resets sourced slots except `city`; `origin` (status `answered`) is kept, but an origin that `public_origin` maps to "Origine non précisée" is stored as `None` (`engine.py:169-171`) and its chip disappears. The jury reported the departure-city chip missing after re-framing; the FE must not drop it. |
| **After** | Chip states (icon is `aria-hidden`, state is in the accessible text): |

| `slot.status` | Icon | Visual | Accessible text | Shown? |
|---|---|---|---|---|
| `unknown` | ○ | dashed outline, muted | "<Label>: not yet known" | yes, max 3, in REQUIRED order |
| `asked` | ◔ | dashed outline, accent | "<Label>: asked" | yes, always (it is the current question) |
| `answered` | ✓ | solid | "<Label>: <value>, from you" | yes |
| `sourced` | ✓ + small "source" dot | solid, link icon; `title` = provenance label | "<Label>: <value>, from <provenance.label>" | yes |
| `not_needed` | — | muted solid | "<Label>: not needed" (e.g. "No budget cap", "Any period") | yes, only for budget and date_window |

Merging rules: (a) **date chip** — show a single "When" chip: if `race_date` is known, show the formatted date (`11 Apr 2027`) and hide `date_window`; else show `date_window`; "Period?" never coexists with a known `race_date`. (b) **race chip** — if `race` is known hide `city`'s "?" chip. (c) **origin chip persists**: BE must keep `origin` as `answered` across `discovery_changed` (it is not in the reset list — keep it so) and must not null an explicit origin; FE must render the origin chip from `slot.value` whenever `status ∈ {answered, sourced}`. (d) chips are ordered: race/city, date, distance, origin, nights, transport, budget. (e) BE sets `status=asked` on the slots of every `open_questions[*].slots` so the FE can distinguish asked vs unknown.

| | |
|---|---|
| **Acceptance** | (a) Fixture `framing_ready`: no chip ending with "?". (b) After choosing a candidate with a `race_date`, the chip list contains the date and no "Period" chip (engine test + static test). (c) Framing test: "Marathon from Lyon" → reply "in Lisbon instead" (discovery change) → `slots.origin.value == "Lyon"` and status `answered`. (d) Each chip has distinct accessible text per state. |

### 6. Suggestion chips map to demo fixtures, English, no dead end (FE + DATA)

| | |
|---|---|
| **Before** | `IDEAS` (`app.js:161`) = "Mon premier semi en octobre", "Un marathon au printemps, depuis Lyon", "Un trail en montagne cet été". In demo mode the fixtures are only Milan marathon 2027-04-11, Lisbon 10K 2027-03-14, Tokyo 10K 2028-06-12 (`fakes.py:23-56`, used by `FixtureCandidateSearch`, `server.py:80`). None of the ideas resolves to a fixture: "half in October" and "mountain trail" end in `fixture_missing` ("Pas de fixture demo…", `candidates.py:68-71`) — a dead end in the demo. |
| **After** | Four English chips; in demo mode each resolves to a fixture; in live mode they are ordinary prompts. |

| # | Chip text (visible) | Demo fixture it resolves to | Expected first Holo turn |
|---|---|---|---|
| 1 | `A spring marathon in Milan, leaving from Lyon` | `DEMO_RACES["milan"]` — 2027-04-11, 42.195 km | candidates (1 card) |
| 2 | `A 10K in Lisbon next March` | `DEMO_RACES["lisbon"]` — 2027-03-14, 10 km | asks origin |
| 3 | `A 10K in Tokyo, flying in` | `DEMO_RACES["tokyo"]` — 2028-06-12, 10 km | asks origin |
| 4 | `My first marathon, anywhere in spring` | closest fixture: `milan` (+ notice) | candidates (1 card, close-match notice) |

Chip text is data, not code: FE reads it from `GET /api/health` → `suggestions: [{text, fixture_key}]` (BE), falling back to the list above, so the static files do not hard-code city names (static tests forbid some city names in `.js`).

**No-dead-end rule (demo/replay):** when `FixtureCandidateSearch` has no exact match, it returns the **closest fixture** (same distance first, then nearest date, then any) as a candidate carrying `Limitation(code="close_match", message="Demo data has no exact match. Closest demo race shown — live mode searches the real web.")`. The engine already phrases close matches ("I couldn't find your exact race. Here are the closest — which one interests you?", `engine.py:453-456`). `fixture_missing` is kept only when the fixture list is empty (replay with no race).

| | |
|---|---|
| **Acceptance** | Demo end-to-end test per chip: `POST /api/framings {text: chip}` then answering only the asked questions reaches `ready_to_confirm` with `summary.race.name` equal to the fixture in the table, in ≤4 replies. A random phrase ("a trail in the Alps") in demo yields ≥1 candidate with a `close_match` limitation, never zero candidates. All chip texts are English. |

### 7. English-first extraction (HOLO + BE)

| | |
|---|---|
| **Before** | `interpret.py` is French-first: `MONTHS` is French only (`interpret.py:8-21`); the city prefix `in` matches the next capitalised word (`interpret.py:28-37`), so English month names become cities. Verified on `3373e01`: "Milan marathon in April 2027" → `{city: "April", distance_km: 42.195}`; "My first half marathon in October" → `{city: "October"}`; "Half marathon in Lisbon next spring, budget 600 euros" → `{city: "Lisbon next spring"}`; "Something in April, from Lyon by car" → `{origin: "Lyon by car", city: "April"}`; "Tokyo 10K on 2028-06-12…" → no city, no distance. |
| **After** | English month and season names are date words, never places; `10K`/`5K`/`half` are distances; "<City> marathon" (city before the race word) yields city; trailing qualifiers ("next spring", "by car", "by train") are cut from place names. Holo's extraction prompt receives these 8 phrases as few-shot / eval cases. |

Acceptance fixtures (copy-paste into `tests/test_framing_extract_english.py`, `today = 2026-11-07`). Slots not listed must be **absent**.

```python
EN_EXTRACTION_CASES = [
    ("Milan marathon in April 2027",
     {"city": "Milan", "distance_km": 42.195, "date_window": "april 2027", "edition": "2027"}),
    ("A spring marathon in Milan, leaving from Lyon",
     {"city": "Milan", "distance_km": 42.195, "date_window": "spring 2027", "origin": "Lyon"}),
    ("I want to run the Lisbon 10K in March 2027 from Bordeaux, 2 nights, by train",
     {"city": "Lisbon", "distance_km": 10.0, "date_window": "march 2027", "edition": "2027",
      "origin": "Bordeaux", "nights": 2, "transport_mode": "train"}),
    ("Half marathon in Lisbon next spring, budget 600 euros",
     {"city": "Lisbon", "distance_km": 21.0975, "date_window": "spring 2027", "budget": 600.0}),
    ("Tokyo 10K on 2028-06-12, flying from Lyon",
     {"city": "Tokyo", "distance_km": 10.0, "race_date": "2028-06-12", "origin": "Lyon",
      "transport_mode": "flight"}),
    ("My first half marathon in October",
     {"distance_km": 21.0975, "date_window": "october 2027"}),
    ("Something in April, from Lyon by car",
     {"date_window": "april 2027", "origin": "Lyon", "transport_mode": "car"}),
    ("Marathon in Milan, leaving from Lyon, 3 nights, no budget",
     {"city": "Milan", "distance_km": 42.195, "origin": "Lyon", "nights": 3, "budget": None}),
]
```

| Phrase | Must NOT yield |
|---|---|
| 1, 6, 7 | `city` = a month name |
| 4 | `city` containing "next" / "spring" |
| 7 | `origin` containing "by car" |
| 5 | missing `distance_km` (10K) |

Notes: season → `"<season> <year>"` where year is the next occurrence after `today`; "October" alone after 2026-11-07 → 2027. If the BE prefers keeping `date_window` free text, the assertion is "contains the month/season and the year". French phrases already covered by `tests/test_framing_engine.py` must keep passing.

| | |
|---|---|
| **Acceptance** | All 8 cases pass `extract_slots(text, today=date(2026, 11, 7))` (heuristic) **or** the heuristic + `HoloPhraser.extract` path in a recorded eval; zero "must NOT" violations. |

### 8. Confirm step: "Ready to launch" card (FE + BE copy)

| | |
|---|---|
| **Before** | `app.js:328-342`: section titled with the race name or "Votre demande, avant lancement"; lines from `summary.lines` (`engine.py:549-553`: "Départ : Lyon ; 2 nuits ; train", "Budget : sans plafond"); primary button "Lancer la recherche"; hint **after** the button: "Trois agents vont naviguer pour vous. Ils s’arrêtent avant tout paiement ou envoi définitif."; the corrections `<details>` is appended inside the card after the hint. Holo line: "Tout est prêt. Vérifiez le récapitulatif avant de lancer la recherche." (`app.js:291`). |
| **After** | Card `section.ready` with `aria-labelledby` its `h2` **"Ready to launch"**; sub-heading = race name. Lines (BE `summary.lines`, English): `"Milano Marathon (demo) · Milan · Sun 11 Apr 2027 · 42.195 km"`, `"From Lyon · 2 nights (10–12 Apr) · train"`, `"Budget: no cap"` / `"Budget: up to €600"`. Limitations listed below the lines. Safety line **before** the button: **"Three agents will browse for you: registration, hotel and transport. They stop before any payment."** Primary button **"Launch the agents"**, `aria-describedby` → safety line. Secondary "Edit something" (`details`) after the button. Holo line: "Everything is ready. Check the summary, then launch the agents." On click: button → disabled "Launching…", status region "Launching the agents…" (item 10); on success the mission screen replaces the framing screen and focus goes to the mission `h1`. |
| **Acceptance** | Fixture `framing_ready`: the card's `h2` text is exactly "Ready to launch"; the safety line precedes the launch button in DOM order and contains "stop before any payment"; the launch button is the only `primary` button on the screen; double click creates one mission (idempotency key unchanged — existing behaviour, `app.js:337`). |

### 9. Visible Pause / Resume / Cancel controls and cancel confirmation (FE)

| | |
|---|---|
| **Before** | The mission screen has **no** visible pause/resume control: pause/resume exist only as voice commands (`onAgentsCommand`, `app.js:218-225`) and as backend routes `POST /api/missions/{id}/pause|resume` and `/steps/{kind}/pause|resume` (`server.py:249-275`). The only "Pause" button is the map player's (`app.js:545`). Cancel is a plain secondary button "Annuler les préparatifs" (`app.js:518-521`) that cancels immediately with no confirmation; framing cancel is "Annuler la demande" (`app.js:351`). |
| **After** | A mission control bar under the mission title (`role="group"`, `aria-label="Agent controls"`): |

| Mission status | Buttons (in order) |
|---|---|
| `running`, `searching`, `waiting_for_user` | **Pause all agents** · **Stop and cancel** |
| `paused` | **Resume agents** (primary) · **Stop and cancel** |
| terminal (`awaiting_human`, `completed`, `failed`, `cancelled`) | none |

Per-step (inside each running step card, optional in this PR): **Pause** / **Resume** with `aria-label="Pause <Registration>"`.
Cancel confirmation — native `<dialog>` (modal, focus trapped, Esc = keep running):

```
Title:   Stop all agents?
Body:    The three agents will stop where they are. Nothing has been paid or
         submitted. RunAI will not continue the pages they
         already filled.
Buttons: [ Keep running ] (default focus)   [ Stop and cancel ] (destructive)
```

Framing cancel ("Cancel request") needs no dialog (no agents launched); after cancel show "Request cancelled. No agent was launched." + **New request**.
After mission cancel: status line "Cancelled · no payment was made." and focus to the mission `h1`.

| | |
|---|---|
| **Acceptance** | (a) With `mission_snapshot` status `running`, buttons "Pause all agents" and "Stop and cancel" are present; with `paused`, "Resume agents" is present and "Pause all agents" is not. (b) Clicking "Stop and cancel" does not call `/cancel` until the dialog's "Stop and cancel" is clicked; "Keep running" and Esc call nothing. (c) Dialog opens with focus on "Keep running", closes returning focus to the bar. |

### 10. Status region copy for SSE and mutations (FE, UX-04)

| | |
|---|---|
| **Before** | French, generic and duplicated: "Envoi en cours…", "Demande acceptée." (`app.js:136-137`), "Conversation mise à jour." (`:140`), "Statut de la mission : <label>" on every status change (`:371`), "Suivi interrompu. La reconnexion ne relance pas les agents." (`:374`), "Reconnexion au suivi en cours…" (`:377`); the framing `say` paragraph is a second `aria-live` region (`app.js:292`), so answers are announced twice. |
| **After** | Only `#feedback` is live (`role="status"`); `say` loses `aria-live` (the Holo line is focused/read via the dock's `aria-describedby`). Messages (one at a time, replaced, cleared after 6 s when `quiet`): |

| Trigger | Message | Tone |
|---|---|---|
| mutation start (framing reply / question answer) | `Sending…` | quiet |
| framing reply accepted | *(none — Holo's next line is the feedback)* | — |
| question answer accepted | `Answer sent to the <Registration> agent.` | quiet |
| confirm clicked | `Launching the agents…` | quiet |
| 409 reload | `This changed in the meantime. Showing the latest version.` | quiet |
| network / 5xx | `Couldn't reach RunAI. Check your connection and try again.` | error |
| SSE `mission_status` → `running` | `Agents are working.` | quiet |
| → `waiting_for_user` | `An agent needs your answer.` | polite (not quiet) |
| → `paused` | `Agents paused.` | quiet |
| → `awaiting_human` | `Agents stopped before payment. Finish on the official sites.` | polite |
| → `completed` | `All set. Nothing was paid.` | polite |
| → `failed` | `An agent failed: <mission.error, first sentence>.` | error |
| → `cancelled` | `Cancelled. No payment was made.` | polite |
| SSE `question_opened` | `New question from the <Registration> agent.` | polite |
| SSE `onerror` while not terminal | `Reconnecting to live updates…` | quiet |
| SSE refresh failed | `Live updates paused. Reloading will not restart the agents.` | error |
| `step` / `trace` / `budget_updated` | *(none — visible in the live view, not announced)* | — |

Rules: announce only status **transitions** (compare previous status), never the same text twice in a row; never announce during typing in an input (queue until blur); max one announcement per 2 s.

| | |
|---|---|
| **Acceptance** | (a) Only one element in the DOM has `aria-live`. (b) A static test drives `running → waiting_for_user → running → awaiting_human` and records `#feedback` texts: exactly the four messages above in order, no duplicates. (c) All strings are English. |

---

## 2. Routing summary for the Chief

| Item | Owner | Lands in |
|---|---|---|
| 1, 2, 5 (FE part), 6 (FE part), 8 (FE part), 9, 10 | Frontend | one `front-night` PR (not auto-merged) |
| 3, 4, 5 (`asked` status, origin persistence), 6 (`suggestions` field, closest-fixture rule), 8 (`summary.lines` English) | Backend | regular PR |
| 7 | Holo / Prompt + Backend | regular PR (`interpret.py` + eval) |
