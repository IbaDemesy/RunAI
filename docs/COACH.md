# Coach — “What kind of runner are you?” (`runai/coach/`)

Five voice questions → runner profile → level, predicted times and distance advice →
3–5 suitable open races with a reason and registration status. English questions and
prompts accept both English and French answers, including code-switching.
No H calls are made: unconfirmed statuses remain `a_verifier` (`needs_h_check=True`)
for a later **read-only** H check.

## API

```python
from runai.coach import QUESTIONS, extract_profile, assess, recommend_races, RacePreferences

transcript = (
    "I run four times a week, roughly forty kilometres. "
    "My longest run was 22 km in 2h05. "
    "I ran a half marathon in 1:48 3 months ago. "
    "I have been running for 3 years and I am 31. "
    "I want to run a marathon while travelling abroad."
)
x = extract_profile(transcript)             # ProfileExtraction
x.profile                                   # CoachProfile, not the identity RunnerProfile
x.follow_up_questions                       # Questions to repeat after clearing suspect fields

a = assess(x.profile)                       # Assessment
a.estimate.level, a.estimate.predictions    # Level and TimeRange per race distance
a.recommended, a.not_advised, a.summary()   # Recommended, discouraged or blocked distances

r = recommend_races(a, RacePreferences(origin_city="Paris", distance_km=42.195), mode="replay")
r.races[0].reason, r.races[0].status         # Reason and registration status
r.races[0].to_race()                        # Race for an existing mission
```

| Function | Role |
| --- | --- |
| `QUESTIONS` | Five English questions: frequency/volume, longest run, recent race, experience/age and goals. `CUSTOM_VOCABULARY` retains French terms alongside English terms for Gladia. |
| `extract_profile(text, llm_json=None)` | Bilingual rules or LLM JSON via `llm_prompt()`, then plausibility checks for pace, longest run vs weekly volume and race bounds. Suspect fields become `None` with follow-up questions. Never guesses: “14 10 km” leaves the field empty. |
| `assess(profile, weeks_available=None)` | Daniels/VDOT, Cooper, training run or self-reported level; Riegel upper bounds; preparation and age safeguards. Marathon preparation under 12 weeks is blocked, beginners need at least 24 weeks, and fewer than three weekly sessions discourages marathons. |
| `recommend_races(assessment, preferences, mode=…)` | `replay`: offline cache only (`CacheMiss` otherwise); `live`: Linkup and cache write; `auto`: cache under 24 hours old (`max_cache_age`), otherwise live. Blocking, typically 20–60 seconds live. |
| `rank_races(assessment, discovery)` | Deterministic offline ranking: named races, then open races, then `a_verifier` to reach three. Excludes full/closed races, dates outside the window, insufficient preparation and duplicates. |

Rules support English number words from one through sixty, kilometres and miles
(1 mile = 1.609344 km), half marathons and marathons, `1h48`, `1:48` (hours:minutes),
and `48 minutes`. “3 months ago”, “I am 31” and “running for 3 years” fill the
corresponding fields. Goal values stay unchanged: first 10K → `premier_10k`,
PR/PB → `chrono`, trail → `trail`, abroad/travel → `voyage`, finish → `finir`.
French answers continue to use the same profile schema.

## Demo mode (cache/fixtures)

`runai/coach/fixtures/*.json` contains raw `DiscoveryResult` objects before ranking,
keyed by `SearchQuery.cache_key()`. Ranking is repeated on read for each profile.
`DEMO_TRANSCRIPT` is English; `DEMO_PREFERENCES` contains `milan` (Wizz Air Milano
Marathon, April 4, 2027; measured Linkup run on November 7, 2026), plus the four
measured spike profiles: `debutant_10k_paris`, `semi_france`, `trail_lyon`, `semi_etranger`.
Regenerate with `recommend_races(a, DEMO_PREFERENCES["milan"], mode="live")`;
this writes fixtures. Use `DiscoveryCache(dir)` for a different directory.

## Measurements

Measured on November 7, 2026: Linkup took 20–61 seconds per profile, costing
$0.04–$0.10 by balance delta; H confirmed 8/12 open races in the spike. Milan:
49 seconds, $0.098 balance delta ($0.152 estimated by `FinderMetrics`, shared key),
five open races including Milan. Njuko SPA pages unreadable by `/fetch` remain
`a_verifier` without H calls.
Confidence bounds, preparation weeks, age caps and trail adjustments still need
coach validation. Travel time uses straight-line distance (ground ×1.3 at 90 km/h;
flight at 750 km/h plus 0.5 hours).

## Proposed integration (not implemented)

- `GET /coach/questions` → `QUESTIONS`; `POST /coach/profile` with a Gladia transcript → `ProfileExtraction`.
- `POST /coach/assess` → `Assessment`; `POST /coach/races` with `RacePreferences` → `Recommendations`,
  using `anyio.to_thread.run_sync` and defaulting to `mode="replay"` for demos.
- Race selection: `RaceRecommendation.to_race()` → existing mission; `needs_h_check` →
  read-only H verification before registration.
