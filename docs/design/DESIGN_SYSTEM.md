# RunAI design system

One visual system for the whole app: framing (Holo dialogue), mission (live agent view) and recap.
Source of truth for values: [`tokens.css`](tokens.css); visual reference: [`specimen.html`](specimen.html) (open locally, it loads `tokens.css`). Verify with `python -m scripts.check_design_tokens`.

## 1. Decision: one dark-first "dawn" system

**Decision.** RunAI keeps the dark *dawn* identity end-to-end: night-blue surfaces (`--surface-0/1/2`), chalk text, a single sun-yellow accent. The mission page stops switching to the light paper palette when framing ends.

**Why.** The product's signature moment is watching autonomous agents work: H browser screenshots, Linkup sources and Gladia transcripts streaming into lanes. On a dark surface, screenshots (mostly white web pages) read as lit windows and status changes stand out, which is the "control room" feeling judges remember. Framing already lives in the dawn palette, so continuing it removes the visual break that every juror flagged ("two disconnected design systems") at the exact moment the agents start. A single accent (sun) can then mean one thing everywhere: *your action / Holo is speaking*. Dark also makes the pre-payment halt card (the one bright, chalk-filled card) the most visible element of the recap.

**Alternative considered: light end-to-end** (paper `#f0eee9`, ink text, yellow accent), as proposed in `docs/FRONTEND.md` §2 ("a clear and calm surface"). Simpler for print/PDF exports and closer to a travel notebook, but it drops the dawn framing screens Iba and Mathieu already polished, makes white H screenshots blend into white cards, and weakens the live-view demo. Keep it only for exports (PDF/.ics recap), where the legacy light tokens remain valid.

## 2. Token roles

`tokens.css` is a drop-in replacement for the `:root` block of `runai/app/static/style.css`. It keeps **every** existing variable name, so nothing breaks, and it still passes `tests/ux_acceptance/checks.py::contrasts` unchanged.

| Family | Tokens | Role |
| --- | --- | --- |
| Dawn | `--night --sun --chalk --mist --haze` | Identity colors. `--chalk` primary text, `--mist` secondary text, `--haze` links and tertiary accents, `--sun` the single accent. Now defined at `:root`; the `body.dawn` values are identical, so that block can drop its copy later. |
| Surfaces | `--surface-0` page, `--surface-1` card / lane, `--surface-2` raised, input, hover; `--border`, `--border-strong` | All dark. Never put `--ink` text on them. |
| Legacy light | `--ink --ink-2 --ink-3 --paper --paper-2 --card --line --accent --gold --gold-soft --ok --bad` | Fixed roles: `--ink*` is **text on bright fills** (sun buttons, chalk bubble, light chips); `--paper*`/`--card` are **bright fills** (user bubble, pre-payment halt card, exports). Values moved from warm beige to the cool dawn hue. `--ok`/`--bad` stay dark green/red for light chips only; on dark use `--text-success`/`--text-error`. |
| Status | `--status-{pending,running,paused,waiting,stopped,completed,failed}-{bg,fg}` | Agent step chips (section 5). |
| Partner | `--partner-h --partner-linkup --partner-gladia --partner-holo --partner-devin` | Partner badge dot/border and label. Readable as text on every surface. Not official brand colors. |
| Mode | `--mode-live --mode-demo --mode-replay` | Dot of the Live / Demo / Replay badge. |
| Focus | `--focus` (sun), `--focus-on-bright` (night), `--focus-width` 3px | `:focus-visible { outline: var(--focus-width) solid var(--focus); outline-offset: 2px; }`; inside bright fills use `--focus-on-bright`. |
| Type | `--display --text --mono --holo-voice`, `--type-{small,body,lead,heading,title,hero}` | Section 3. |
| Space / radius | `--space-{1,2,3,4,6,8,12}`, `--radius-{small,card,lane,pill}` | Section 4. |
| Buttons | `--button-bg --button-text` (legacy), `--button-min`, `--button-{primary,secondary,danger}-{bg,fg}`, `--button-quiet-fg` | Section 5. |
| Motion | `--motion-fast` 150ms, `--motion-chapter` 400ms, `--ease` | Section 6. Both drop to `0ms` under `prefers-reduced-motion`. |
| Local | `--icon` | Component-local mask URL for icon buttons; default `none`. |

## 3. Typography

- **Display: Archivo** (`--display`), weight 600–800, for page titles, lane titles, race name, prices. `font-stretch` 85–118% is allowed; one width per screen.
- **Text: Geist** (`--text`), 400/500/600, for everything else: body, labels, buttons, chips.
- **Mono: Geist Mono** (`--mono`) **only for URLs** (current agent URL, source links). Never for prose, timestamps or IDs shown to the user.
- **Holo voice: Courier Prime** (`--holo-voice`) is limited to Holo's single typewriter line (`.say`) in framing. **Open decision for Mathieu/Iba:** today `body.dawn *` forces Courier Prime on every element; this system recommends restricting it to `.say` so the live view and lanes stay in Geist.
- Scale: `--type-small` .875rem (meta, chips), `--type-body` 1rem, `--type-lead` 1.125rem (hero sub, Holo line on mobile), `--type-heading` 1.375rem (lane title), `--type-title` (page title), `--type-hero` (framing hero). Line height 1.5 for text, 1.0–1.15 for display.
- Two families on screen at most (display + text); mono and Holo voice are scoped exceptions.

## 4. Spacing and radius

- 4px grid: `--space-1` 4, `--space-2` 8, `--space-3` 12, `--space-4` 16, `--space-6` 24, `--space-8` 32, `--space-12` 48. Inside a card use 8–16; between cards 16–24; between sections 32–48.
- Radius: `--radius-small` 8 (inputs, URL box, thumbnails), `--radius-card` 14 (cards, questions), `--radius-lane` 18 (agent lanes, candidate cards, halt card), `--radius-pill` 999 (buttons, chips, badges).
- Max content width 1200px; framing column 720px.

## 5. Components

### Buttons (min 44 × 44px, `--button-min`)

| Variant | Fill / text | Use |
| --- | --- | --- |
| Primary | `--button-primary-bg` sun / `--button-primary-fg` night | One per view: "Start my trip", "Send answer". |
| Secondary | `--button-secondary-bg` surface-2 / chalk, 1px `--border` | Reply suggestions, "Pause", "Edit". |
| Quiet | no fill, `--button-quiet-fg` mist, underline on hover | "Show details", "Start over". |
| Danger | `--button-danger-bg` / `--button-danger-fg` | "Stop this agent", "Cancel mission". Always confirm. |

Rules: pill radius, Geist 600, `--motion-fast` color transition only; disabled = 40% opacity plus `cursor: not-allowed` and an explanation nearby; icon-only buttons need `aria-label`. The current 3D "cosy relief" (stacked shadows + gradient) is replaced by flat fills (see section 7).

### Status chip (agent step, 8 states from `docs/FRONTEND.md` §4)

A pill with a glyph **and** a word, so meaning is never carried by color alone. Backend values from `runai/models.py::StepStatus`.

| UI state | `StepStatus` | Tokens | Glyph | Label |
| --- | --- | --- | --- | --- |
| Pending | `pending` | `--status-pending-*` | ○ | Waiting to start |
| Running | `running` | `--status-running-*` | ● (progress pulse) | Working |
| Pause requested | `running` + local pause sent | `--status-paused-*`, dashed border | ‖ | Pausing… |
| Paused | `paused` | `--status-paused-*` | ‖ | Paused |
| Needs you | `waiting_for_user` | `--status-waiting-*` | ? | Your answer needed |
| Stopped before payment | `stopped_before_commitment` | `--status-stopped-*` | ■ | Ready, stopped before payment |
| Failed | `failed` | `--status-failed-*` | ! | Failed, see why |
| Done | `completed` | `--status-completed-*` | ✓ | Done |

Waiting uses the sun accent on purpose: it is the only state that asks the user to act. Running uses haze so it does not compete with it.

### Partner badge

Small pill on `--surface-2`, 1px border and 8px dot in `--partner-*`, label in the same token: "H agent", "Linkup", "Gladia", "Holo", "Devin". Shown on each lane header and each source line so judges see which partner did what. Never more than one partner badge per row.

### Mode badge

Header pill: dot `--mode-live` + "Live", `--mode-demo` + "Demo", `--mode-replay` + "Replay". Text in chalk on `--surface-2`. The Live dot may pulse with `--motion-fast` unless reduced motion is on. Unknown mode shows "Mode unknown" with no dot.

### Card

`--surface-1` fill, 1px `--border`, `--radius-card`, padding `--space-4`–`--space-6`, no shadow. Title in display, meta in mist at `--type-small`. The **pre-payment halt card** is the only inverted card: `--card` fill, `--ink` text, a 4px sun top border.

### Lane (live agent view)

One lane per agent (Registration, Accommodation, Transport): `--surface-1`, `--radius-lane`, header = title + partner badge + status chip, then the latest H screenshot (16:9, `--radius-small`, 1px `--border`), the current step in plain English ("Filling in the runner form"), the current URL in mono mist (truncated, full URL in title), and sources as they arrive. Running lanes get a 2px `--status-running-bg` left border; waiting lanes a sun one. Lanes stack in one column below 768px.

### Details / summary

For technical detail (session IDs, raw trace, step count): `summary` in quiet button style with a ▸ / ▾ glyph, body on `--surface-2`. Collapsed by default. Never hide a pending question inside one.

### Link with external icon

Haze text, underline offset 3px, followed by a 12px "↗" icon (`aria-hidden`), and the accessible name ends with "(opens in a new tab)". `target="_blank" rel="noopener"`. On bright fills use `--ink`.

## 6. Motion

- Allowed: progress (running dot, step bar fill, typing dots while Holo thinks) and chapter changes (lane appears, screenshot swap, framing → mission). Use `--motion-fast` for state feedback and `--motion-chapter` for chapter changes, with `--ease`.
- Every animation is interruptible: no animation blocks input or delays focus; a new SSE event cancels the running transition.
- `prefers-reduced-motion: reduce` sets both durations to `0ms` in `tokens.css`, and the existing `animation: none !important; transition: none !important` rule stays in `style.css`.
- No autoscroll that moves content the user is reading; announce changes through the `role="status"` live region instead.

## 7. What to remove

- Decorative gradients: hero sky gradient, gradient-filled candidate cards, glossy "cosy relief" buttons, radial-gradient Holo dot and record button, rainbow sheen on the runner. Flat token fills only.
- Stacked decorative shadows and backdrop blur on the ask bar; one 1px border is enough.
- Raw ISO timestamps (`2026-11-07T21:04:12Z`) in the trace and lanes: show "2 min ago" or "21:04".
- Developer jargon in the main view: "SSE", "SDK", "session", "trajectory", "H step 37", raw enum values like `waiting_for_user`. Keep them inside details/summary.
- Hard-coded colors in `style.css` (`#fff`, `#e3f1e8`, `#fbe6e8`, `#c9c7c2`, `#2a2a2d`, `#3ddc84`, `#ffb4a8`…): replace with tokens.
- The light `body` background on the mission page and the `body.dawn` toggle in `app.js` once migration is done.

## 8. Migration map for the frontend PR (`front-night`)

Not applied here: `runai/app/static/*` is owned by Mathieu.

1. Replace the `:root` block of `style.css` with the one in `tokens.css` (safe: names kept, acceptance contrasts pass).
2. Switch selectors from the light roles to the dark ones: `body` background `--paper` → `--surface-0`, text `--ink` → `--chalk`; `.step`, `.trace`, `.bib`, `.message input` background `--card` → `--surface-1`, borders `--line` → `--border`; `.last-action`, `.facts dt`, `.sources` `--ink-2/3` → `--mist`; `.current-url` → `--mono` + `--mist` on `--surface-2`; `.status-*` → `--status-*-bg/fg`; `a` → `--haze`; `:focus-visible` → `--focus`.
3. Keep bright fills where they carry meaning: user bubble, pre-payment halt card, sun primary buttons.
4. Then `body.dawn` can stop redefining the dawn colors and the `classList.toggle("dawn")` becomes a no-op.
5. Extend `tests/ux_acceptance/checks.py::contrasts` with the dark pairs from `scripts/check_design_tokens.py` once step 2 lands (the current pairs assume a light page).

## 9. Contrast table

Computed with the WCAG relative-luminance formula used by `tests/ux_acceptance/checks.py::contrast_ratio` (imported, not copied). Text pairs need ≥ 4.5; non-text UI parts (focus ring, mode dot, strong border) need ≥ 3. Regenerate with `python -m scripts.check_design_tokens --markdown`; `tests/test_design_tokens.py` fails if this table is stale.

| Group | Foreground | Background | Ratio | Min |
| --- | --- | --- | ---: | ---: |
| Text on dark | `--chalk` #f5f7fb | `--surface-0` #0f1b33 | 15.98 | 4.5 |
| Text on dark | `--chalk` #f5f7fb | `--surface-1` #16264a | 13.88 | 4.5 |
| Text on dark | `--chalk` #f5f7fb | `--surface-2` #1e3160 | 11.77 | 4.5 |
| Text on dark | `--mist` #b9c3d6 | `--surface-0` #0f1b33 | 9.67 | 4.5 |
| Text on dark | `--mist` #b9c3d6 | `--surface-1` #16264a | 8.40 | 4.5 |
| Text on dark | `--mist` #b9c3d6 | `--surface-2` #1e3160 | 7.12 | 4.5 |
| Text on dark | `--haze` #8fb3e8 | `--surface-0` #0f1b33 | 7.99 | 4.5 |
| Text on dark | `--haze` #8fb3e8 | `--surface-1` #16264a | 6.94 | 4.5 |
| Text on dark | `--haze` #8fb3e8 | `--surface-2` #1e3160 | 5.88 | 4.5 |
| Text on dark | `--sun` #ffd84d | `--surface-0` #0f1b33 | 12.39 | 4.5 |
| Text on dark | `--sun` #ffd84d | `--surface-1` #16264a | 10.77 | 4.5 |
| Text on dark | `--sun` #ffd84d | `--surface-2` #1e3160 | 9.13 | 4.5 |
| Text on dark | `--text-error` #ffb4a8 | `--surface-0` #0f1b33 | 10.08 | 4.5 |
| Text on dark | `--text-error` #ffb4a8 | `--surface-1` #16264a | 8.75 | 4.5 |
| Text on dark | `--text-error` #ffb4a8 | `--surface-2` #1e3160 | 7.42 | 4.5 |
| Text on dark | `--text-success` #86e5ae | `--surface-0` #0f1b33 | 11.29 | 4.5 |
| Text on dark | `--text-success` #86e5ae | `--surface-1` #16264a | 9.81 | 4.5 |
| Text on dark | `--text-success` #86e5ae | `--surface-2` #1e3160 | 8.32 | 4.5 |
| Partner label | `--partner-h` #ff9b6b | `--surface-0` #0f1b33 | 8.29 | 4.5 |
| Partner label | `--partner-h` #ff9b6b | `--surface-1` #16264a | 7.20 | 4.5 |
| Partner label | `--partner-h` #ff9b6b | `--surface-2` #1e3160 | 6.10 | 4.5 |
| Partner label | `--partner-linkup` #5fd6b5 | `--surface-0` #0f1b33 | 9.61 | 4.5 |
| Partner label | `--partner-linkup` #5fd6b5 | `--surface-1` #16264a | 8.35 | 4.5 |
| Partner label | `--partner-linkup` #5fd6b5 | `--surface-2` #1e3160 | 7.08 | 4.5 |
| Partner label | `--partner-gladia` #c9a7ff | `--surface-0` #0f1b33 | 8.54 | 4.5 |
| Partner label | `--partner-gladia` #c9a7ff | `--surface-1` #16264a | 7.41 | 4.5 |
| Partner label | `--partner-gladia` #c9a7ff | `--surface-2` #1e3160 | 6.29 | 4.5 |
| Partner label | `--partner-holo` #ffd84d | `--surface-0` #0f1b33 | 12.39 | 4.5 |
| Partner label | `--partner-holo` #ffd84d | `--surface-1` #16264a | 10.77 | 4.5 |
| Partner label | `--partner-holo` #ffd84d | `--surface-2` #1e3160 | 9.13 | 4.5 |
| Partner label | `--partner-devin` #7cc4ff | `--surface-0` #0f1b33 | 9.14 | 4.5 |
| Partner label | `--partner-devin` #7cc4ff | `--surface-1` #16264a | 7.94 | 4.5 |
| Partner label | `--partner-devin` #7cc4ff | `--surface-2` #1e3160 | 6.73 | 4.5 |
| Status chip | `--status-pending-fg` #b9c3d6 | `--status-pending-bg` #22345c | 6.91 | 4.5 |
| Status chip | `--status-running-fg` #0f1b33 | `--status-running-bg` #8fb3e8 | 7.99 | 4.5 |
| Status chip | `--status-paused-fg` #dfe6f2 | `--status-paused-bg` #2a3a5e | 8.97 | 4.5 |
| Status chip | `--status-waiting-fg` #0f1b33 | `--status-waiting-bg` #ffd84d | 12.39 | 4.5 |
| Status chip | `--status-stopped-fg` #0f1b33 | `--status-stopped-bg` #f5f7fb | 15.98 | 4.5 |
| Status chip | `--status-completed-fg` #86e5ae | `--status-completed-bg` #123d2b | 8.00 | 4.5 |
| Status chip | `--status-failed-fg` #ffb4a8 | `--status-failed-bg` #4a1824 | 8.53 | 4.5 |
| Button | `--button-primary-fg` #0f1b33 | `--button-primary-bg` #ffd84d | 12.39 | 4.5 |
| Button | `--button-secondary-fg` #f5f7fb | `--button-secondary-bg` #1e3160 | 11.77 | 4.5 |
| Button | `--button-danger-fg` #ffb4a8 | `--button-danger-bg` #4a1824 | 8.53 | 4.5 |
| Button | `--button-quiet-fg` #b9c3d6 | `--surface-0` #0f1b33 | 9.67 | 4.5 |
| Button | `--button-quiet-fg` #b9c3d6 | `--surface-1` #16264a | 8.40 | 4.5 |
| Button | `--button-quiet-fg` #b9c3d6 | `--surface-2` #1e3160 | 7.12 | 4.5 |
| Bright fill | `--ink` #0f1b33 | `--card` #f5f7fb | 15.98 | 4.5 |
| Bright fill | `--ink` #0f1b33 | `--paper` #eef2f8 | 15.26 | 4.5 |
| Bright fill | `--ink` #0f1b33 | `--paper-2` #e4eaf3 | 14.17 | 4.5 |
| Bright fill | `--ink` #0f1b33 | `--accent` #ffd84d | 12.39 | 4.5 |
| Bright fill | `--ink` #0f1b33 | `--gold-soft` #ffefaa | 14.84 | 4.5 |
| Legacy light | `--ink-2` #2b3a58 | `--paper` #eef2f8 | 10.11 | 4.5 |
| Legacy light | `--ink-2` #2b3a58 | `--paper-2` #e4eaf3 | 9.39 | 4.5 |
| Legacy light | `--ink-2` #2b3a58 | `--card` #f5f7fb | 10.59 | 4.5 |
| Legacy light | `--ink-3` #46536f | `--paper` #eef2f8 | 6.85 | 4.5 |
| Legacy light | `--ink-3` #46536f | `--paper-2` #e4eaf3 | 6.37 | 4.5 |
| Legacy light | `--ink-3` #46536f | `--card` #f5f7fb | 7.18 | 4.5 |
| Legacy light | #fff | `--ink` #0f1b33 | 17.14 | 4.5 |
| Legacy light | `--button-text` #f5f7fb | `--button-bg` #0f1b33 | 15.98 | 4.5 |
| Legacy light | `--ok` #237242 | #e3f1e8 | 5.06 | 4.5 |
| Legacy light | `--bad` #c81e2d | #fbe6e8 | 4.78 | 4.5 |
| Non-text | `--focus` #ffd84d | `--surface-0` #0f1b33 | 12.39 | 3 |
| Non-text | `--focus` #ffd84d | `--surface-1` #16264a | 10.77 | 3 |
| Non-text | `--focus` #ffd84d | `--surface-2` #1e3160 | 9.13 | 3 |
| Non-text | `--focus-on-bright` #0f1b33 | `--sun` #ffd84d | 12.39 | 3 |
| Non-text | `--focus-on-bright` #0f1b33 | `--chalk` #f5f7fb | 15.98 | 3 |
| Non-text | `--mode-live` #3ddc84 | `--surface-0` #0f1b33 | 9.61 | 3 |
| Non-text | `--mode-live` #3ddc84 | `--surface-1` #16264a | 8.35 | 3 |
| Non-text | `--mode-live` #3ddc84 | `--surface-2` #1e3160 | 7.08 | 3 |
| Non-text | `--mode-demo` #ffd84d | `--surface-0` #0f1b33 | 12.39 | 3 |
| Non-text | `--mode-demo` #ffd84d | `--surface-1` #16264a | 10.77 | 3 |
| Non-text | `--mode-demo` #ffd84d | `--surface-2` #1e3160 | 9.13 | 3 |
| Non-text | `--mode-replay` #8fb3e8 | `--surface-0` #0f1b33 | 7.99 | 3 |
| Non-text | `--mode-replay` #8fb3e8 | `--surface-1` #16264a | 6.94 | 3 |
| Non-text | `--mode-replay` #8fb3e8 | `--surface-2` #1e3160 | 5.88 | 3 |
| Non-text | `--border-strong` #5a74a8 | `--surface-0` #0f1b33 | 3.67 | 3 |
| Non-text | `--border-strong` #5a74a8 | `--surface-1` #16264a | 3.19 | 3 |
