"""Audit 2: SSE back-pressure, question/step races, screenshot access and retention, replay privacy."""

import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runai.app.capture_store import PNG_MAGIC, CaptureStore
from runai.app.mission import Mission, MissionStatus
from runai.app.replay_export import export_replay
from runai.app.screenshots import build_screenshot_router
from runai.h.lifecycle import HJob, HLifecycle
from runai.h.runner import HAccount, HRunner
from runai.models import RunnerProfile, StepKind, StepResult, StepStatus, TraceEvent
from runai.tracing import TraceWriter
from tests.test_app import AGENT_KINDS, make_service, unit_plan


def _service_with_mission(tmp_path):
    service = make_service(tmp_path)
    mission = Mission(id="audit2r", query="race", plan=unit_plan(), steps={k: StepResult(kind=k) for k in AGENT_KINDS})
    service.missions[mission.id] = mission
    service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp_path)
    return service, mission


def _observe(service, mission, count):
    for i in range(count):
        service._record(mission, TraceEvent(
            source="h", type="AgentEvent.observation_event", message=f"obs {i}",
            data={"step": "registration", "event": {"data": {"metadata": {"url": f"https://race.example/p{i}"}}}},
        ))


@pytest.mark.anyio
async def test_slow_sse_subscriber_is_dropped_not_buffered_forever(tmp_path, monkeypatch):
    import runai.app.mission as mission_module

    monkeypatch.setattr(mission_module, "SUBSCRIBER_QUEUE_SIZE", 5)
    service, mission = _service_with_mission(tmp_path)
    mission.status = MissionStatus.running
    stream = service.subscribe_events(mission.id)
    pump = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.05)
    queue = next(iter(service._event_subscribers[mission.id]))
    assert queue.maxsize == 5
    _observe(service, mission, 10)  # the consumer is not reading: the queue overflows
    assert queue not in service._event_subscribers[mission.id]
    assert queue.qsize() <= 5
    pump.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pump


@pytest.mark.anyio
async def test_overflowed_stream_ends_so_the_client_can_resume(tmp_path, monkeypatch):
    import runai.app.mission as mission_module

    monkeypatch.setattr(mission_module, "SUBSCRIBER_QUEUE_SIZE", 3)
    service, mission = _service_with_mission(tmp_path)
    mission.status = MissionStatus.running
    stream = service.subscribe_events(mission.id, f"{mission.id}:{len(mission.envelopes)}")
    consumer = asyncio.create_task(_collect(stream))
    await asyncio.sleep(0.05)
    for _ in range(30):
        _observe(service, mission, 1)  # no await: the consumer cannot drain in between
    received = await asyncio.wait_for(consumer, 2)
    assert len(received) <= 3


async def _collect(stream):
    return [event async for event in stream]


@pytest.mark.anyio
async def test_answered_question_does_not_resurrect_a_failed_step(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    service.question_timeout_s = 5
    step = mission.steps[StepKind.registration]
    asking = asyncio.create_task(service.ask(mission.id, StepKind.registration, "Which size?", ["S", "M"]))
    await asyncio.sleep(0.05)
    assert step.status is StepStatus.waiting_for_user
    step.status = StepStatus.failed  # e.g. host drift cancelled the session while the question was open
    service.questions.cancel(next(iter(service.questions.questions)))
    with pytest.raises(Exception, match="human stop maintained"):
        await asking
    assert step.status is StepStatus.failed


def test_replay_export_masks_real_profile_values_in_free_text(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    profile = RunnerProfile(first_name="Jeanne", last_name="Dupontel", email="jd@real.fr", fictional=False,
                            license_number="LIC-998877", emergency_contact_name="Marcel Dupontel")
    service._record(mission, TraceEvent(
        source="h", type="session_created", message="Fill Jeanne Dupontel LIC-998877",
        data={"step": "registration", "emergency_contact_name": "Marcel", "task": "contact marcel dupontel"},
    ))
    mission.status = MissionStatus.completed
    text = export_replay(mission, profile).model_dump_json()
    for private in ("Jeanne", "Dupontel", "LIC-998877", "Marcel"):
        assert private not in text
    assert "Jeanne" in export_replay(mission).model_dump_json()  # no profile given: unchanged behaviour


def test_screenshot_purge_removes_empty_dirs_and_stale_index(tmp_path):
    store = CaptureStore(tmp_path)
    store._write("old1", "accommodation", PNG_MAGIC + b"x", [{"revision": 1}])
    frame = store.frame_path("old1", "accommodation", 1)
    expired = time.time() - 25 * 3600
    os.utime(frame, (expired, expired))
    store.purge()  # expired frame removed; the directory is too recent to be dropped (a write may be starting)
    assert not frame.exists()
    os.utime(frame.parent, (expired, expired))
    store.purge()
    assert not frame.parent.exists() and not (store.root / "old1").exists()


def test_stored_screenshots_require_a_known_mission(tmp_path):
    service, mission = _service_with_mission(tmp_path)
    service.capture_store._write("ghost", "accommodation", PNG_MAGIC + b"x", [{"revision": 1}])
    service.capture_store._write(mission.id, "accommodation", PNG_MAGIC + b"x", [{"revision": 1}])
    app = FastAPI()
    app.include_router(build_screenshot_router(service))
    client = TestClient(app)
    assert client.get("/api/missions/ghost/steps/accommodation/screenshots/1.png").status_code == 404
    assert client.get("/api/missions/ghost/steps/accommodation/screenshots").status_code == 404
    ok = client.get(f"/api/missions/{mission.id}/steps/accommodation/screenshots/1.png")
    assert ok.status_code == 200 and "no-store" in ok.headers["cache-control"]


@pytest.mark.anyio
async def test_watchdog_fires_again_on_a_retried_attempt(tmp_path):
    runner = HRunner(accounts=[HAccount("K", client=SimpleNamespace(sessions=None), max_concurrency=1)], traces_dir=tmp_path)
    lifecycle = HLifecycle(runner, watchdog_interval_s=0.01)
    job = HJob(job_id="j", kind=StepKind.search, mission_id="m")
    job.watchdog.append("force_answer_near_budget")  # fired during a previous attempt
    forced = []

    async def force_answer():
        forced.append(1)

    run = SimpleNamespace(status="running", metrics={"steps": 9}, last_url="u", event_count=0, force_answer=force_answer)
    task = asyncio.create_task(lifecycle._watchdog(job, run, {"max_steps": 10}, None))
    await asyncio.sleep(0.1)
    task.cancel()
    assert forced == [1]
