# Live-view key-path contracts

`test_events_v1_snapshot.py` runs a complete, local demo mission, answers its
questions, and stops before payment. No partner credits or network calls are
required. The goldens record sorted payload key paths by observed SSE event type
(`events.v1`) and the final GET snapshot (`mission.v2`), never values, timestamps,
or generated IDs. Arrays use `[]`, including empty arrays. Current payloads have
no dynamically keyed ID maps. Only event types exercised by this demo are covered;
this is not an exhaustive snapshot of the EventType union or error scenarios.

## Additive-only policy

Removing an observed event type or key path fails with its name. Adding a key
passes and prints the additions (use `-s` to see output on passing tests).
This checks the union of paths across events of each type, not every individual
occurrence or value types. Separate assertions cover live-view invariants.

Update from the repository root with:

```sh
.venv/bin/pytest -q tests/contracts/test_events_v1_snapshot.py --update-golden -s
```

The flag is registered by the local `tests/contracts/conftest.py`. Explicitly
select that test path when updating so pytest loads the option during startup.
Updates still reject removals; review deliberate breaking changes separately.
Commit both golden JSON files together with any intentional contract update.

## Known contract gaps

Three separate strict expected-failure tests track backend gaps on main:

- Pending SSE steps have neither a meaningful headline nor summary.
- Pending SSE steps have no `data.provenance.mode`.
- V2 SSE `StepResult` serialization omits `human_action` even when a step is
  `stopped_before_commitment`; the legacy snapshot's enrichment is not used here.

Supported invariants remain hard assertions: kind/status, valid mode whenever
provenance is present, required question fields, contiguous sequences, and no
forbidden screenshot/authorization keys at any depth in traces. When a backend
gap is fixed, its strict XPASS fails the suite: remove that marker and retain the
assertion. Do not weaken these tests to accommodate regressions.
