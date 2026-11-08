"""Measure SSE envelope growth for N observation events (audit M7). Usage: python scripts/measure_m7.py 40"""

import json
import sys
import tempfile
import time
from pathlib import Path

from runai.app.mission import Mission
from runai.models import StepResult, TraceEvent
from runai.tracing import TraceWriter
from tests.test_app import AGENT_KINDS, make_service, unit_plan

count = int(sys.argv[1]) if len(sys.argv) > 1 else 40
tmp = Path(tempfile.mkdtemp())
service = make_service(tmp)
mission = Mission(id="m7", query="race", plan=unit_plan(), steps={k: StepResult(kind=k) for k in AGENT_KINDS})
service.missions[mission.id] = mission
service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp)
started = time.time()
for i in range(count):
    kind = AGENT_KINDS[i % 3].value
    service._record(mission, TraceEvent(
        source="h", type="AgentEvent.observation_event", message=f"obs {i}",
        data={"step": kind, "event": {"data": {"metadata": {"url": f"https://race.example/p{i}", "title": "t"}}}},
    ))
elapsed = time.time() - started
size = sum(len(json.dumps(e.payload)) for e in mission.envelopes)
print(f"{count} events -> {len(mission.envelopes)} envelopes, {size // 1024} KB, {elapsed:.2f}s")
if "--detail" in sys.argv:
    for e in mission.envelopes[-3:]:
        print(e.type, len(json.dumps(e.payload)))
    step = [e for e in mission.envelopes if e.type == "step"][-1].payload["steps"][0]
    print({k: len(json.dumps(v)) for k, v in step["data"].items()})
