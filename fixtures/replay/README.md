# Offline replay fallback

`default.json` is a complete `replay.v1` recording of a Milan mission launched
through the framing API with `RUNAI_MODE=demo RUNAI_DEMO_DELAY=0.2`.
Its `recorded_mode` is **`demo`**, not `live`: race details, prices, URLs and agent
actions are synthetic, not evidence of availability or successful real bookings.
The fixture's date is synthetic too; it is not the verified race date.
English captions were translated from the recorded demo output; step outcomes,
events and pre-commitment stop points were preserved. Stale demo-view paths were
removed. Registration stops before consent; accommodation and transport stop
before payment. Nothing is submitted or paid.

Start the fallback from the repository root (no partner credentials required):

```sh
RUNAI_MODE=replay .venv/bin/python -m runai.app
```

`GET /api/health` reports `mode: replay`. Complete the framing flow for Milan,
choose the recorded race, confirm, and answer the recorded starting-group and
travel-time questions. All three steps replay their saved events and results with
`provenance.mode: replay`; no partner network calls are made. The trace also
provides an English transcript for the replay voice endpoint.

## Record a real mission in the morning

Run one live mission through framing and wait until all three steps have stopped
before any payment or binding commitment. Then run this exact command from the
repository root, replacing `MISSION_ID` with that mission's ID:

```sh
.venv/bin/python scripts/record_replay.py --base-url http://127.0.0.1:8000 --mission MISSION_ID --output fixtures/replay/live-milan.json --label "Milan Marathon live mission" --transcript "Prepare my Milan Marathon trip, including registration, two nights of accommodation and return travel. Stop before payment or any binding commitment."
```

The current mission snapshot endpoint does not include raw events, so the recorder
merges the server's `traces/MISSION_ID.jsonl` using `TraceWriter.read()`. Run beside
the server's trace files, set `RUNAI_TRACES_DIR`, or add `--traces-dir PATH` for a
copied directory. A snapshot containing `events` can also be passed with
`--snapshot PATH`. Use `--race-json PATH` for an explicit Race JSON override.
The existing trace serializer redacts configured partner credentials; review the
recording for personal information and source quality before committing it.

Select a different trace explicitly without changing the offline default:

```sh
RUNAI_MODE=replay RUNAI_REPLAY_TRACE=fixtures/replay/live-milan.json .venv/bin/python -m runai.app
```

Do not replace `default.json` with an incomplete live run or relabel simulated
output as live. Every replay must retain registration, accommodation and transport
events and preserve the pre-payment / pre-commitment halt.
