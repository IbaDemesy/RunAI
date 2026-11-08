"""Audit 2: mission event growth (M7), store flush off the event loop, asyncio races."""

import asyncio
import json

import pytest

from runai.app.mission import STEP_EVENT_HISTORY_LIMIT, Mission
from runai.app.store import MissionStore
from runai.models import StepResult, TraceEvent
from runai.tracing import TraceWriter
from tests.test_app import AGENT_KINDS, make_service, unit_plan


def _service_with_mission(tmp_path):
    service = make_service(tmp_path)
    mission = Mission(id="audit2", query="race", plan=unit_plan(), steps={k: StepResult(kind=k) for k in AGENT_KINDS})
    service.missions[mission.id] = mission
    service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp_path)
    return service, mission


def _observe(service, mission, count):
    for i in range(count):
        service._record(mission, TraceEvent(
            source="h", type="AgentEvent.observation_event", message=f"obs {i}",
            data={"step": "registration", "event": {"data": {"metadata": {"url": f"https://race.example/p{i}"}}}},
        ))


def test_step_envelopes_bound_embedded_history_and_stay_linear(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    _observe(service, mission, 60)
    last = [e for e in mission.envelopes if e.type == "step"][-1].payload["steps"][0]["data"]
    assert len(last["history"]) == STEP_EVENT_HISTORY_LIMIT
    assert last["history_total"] == 60 and last["history_truncated"] is True
    assert last["history"][-1]["message"] == "obs 59"
    sizes = [len(json.dumps(e.payload)) for e in mission.envelopes if e.type == "step"]
    assert max(sizes) < 2 * sizes[STEP_EVENT_HISTORY_LIMIT + 5]
    # the REST snapshot keeps a longer history, flagged when it is cut
    snapshot = service.snapshot(mission.id).model_dump(mode="json")
    assert len(snapshot["steps"][0]["data"]["history"]) == 60


def test_short_history_has_no_truncation_flag(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    _observe(service, mission, 3)
    data = [e for e in mission.envelopes if e.type == "step"][-1].payload["steps"][0]["data"]
    assert len(data["history"]) == 3 and "history_truncated" not in data


def test_snapshot_not_built_without_subscribers(tmp_path, monkeypatch):
    service, mission = _service_with_mission(tmp_path)
    calls = []
    original = Mission.snapshot
    monkeypatch.setattr(Mission, "snapshot", lambda self, *a, **k: calls.append(1) or original(self, *a, **k))
    _observe(service, mission, 5)
    assert calls == []


@pytest.mark.anyio
async def test_store_background_flush_writes_latest_document_off_loop(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    store = MissionStore(tmp_path)
    mission_id = mission.id
    service._store = store
    _observe(service, mission, 1)  # first save is immediate
    for i in range(30):
        _observe(service, mission, 1)
    await asyncio.sleep(1.3)
    document = json.loads((tmp_path / "missions" / f"{mission_id}.json").read_text(encoding="utf-8"))
    assert document["snapshot"]["sequence"] == len(mission.envelopes) == len(document["envelopes"])
    assert store._encoded[mission_id] and len(store._encoded[mission_id]) == len(mission.envelopes)
    assert not store._background
