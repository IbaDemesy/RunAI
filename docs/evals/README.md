# Framing extraction evaluation

Run from the repository root:

```sh
.venv/bin/python -m scripts.eval_framing
.venv/bin/python -m scripts.eval_framing --no-history
HAI_API_KEY=... .venv/bin/python -m scripts.eval_framing --live
.venv/bin/python -m scripts.eval_framing --fixtures tests/fixtures/framing_evals.jsonl
```

Offline extraction uses a fixed date of 2026-11-07 and needs no network. Live
evaluation is opt-in, forbidden in CI, and requires an exported HAI_API_KEY. It
uses HoloPhraser with holo4-35b-a3b and four concurrent calls, restricting both
sides to EXTRACTABLE slots. HoloPhraser supplies the actual current date in live
mode, so month-only live results can drift over time. HTTP error responses abort
without writing history, as do transport errors and timeouts. HoloPhraser can
still return an empty extraction on a malformed response; inspect unexpectedly
missing live slots accordingly. The initial live attempts with both provisioned
keys returned HTTP 429, so no live baseline or fabricated live history was saved.

Each fixture is a complete desired extraction, not a snapshot of today's bugs.
French utterances and French month values are intentional multilingual test data.
Absent expected keys must remain empty. `pending_u1` marks the 11 cases that fail
on the initial main-code baseline; do not change expectations to hide failures.
The baseline is 39/50 (78%). Remove pending tags as extractor fixes land.

Exact match compares the full slot set after case/accent/outer-whitespace
normalization and absolute numeric tolerance 0.01. Wrong fills are unexpected or
incorrect predicted values; missing counts expected keys absent from prediction.
A wrong value counts as both FP and FN for slot precision/recall, but is not an
absent-key missing. Undefined precision/recall is printed as zero. Empty suites
have exact match zero. Failures include expected/predicted values for diagnosis.

The table includes all cases, the safety-critical `must_not_misfill` subset, and
all cases without `pending_u1`. Tests additionally require zero wrong fills on the
intersection of safety-critical and non-pending cases, exact matches for every
non-pending case, and no regression below the full-suite baseline.

Unless `--no-history` is supplied, successful runs append aggregate metrics,
UTC timestamp, source Git SHA, duration, and live model to
`docs/evals/framing_history.jsonl`. These are rates in [0, 1], not percentages.
Offline and live rates are not directly comparable because live excludes distance,
edition, and exact race date. Commit deliberate baseline runs, not every local run.
