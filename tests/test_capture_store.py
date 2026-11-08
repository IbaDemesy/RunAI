import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runai.app.capture_store import MAX_FRAMES, PNG_MAGIC, CaptureStore
from runai.app.mission import Mission, MissionService
from runai.app.replay import ReplayRun, ReplayStep, ReplayTrace
from runai.app.screenshots import build_screenshot_router
from runai.models import StepKind, StepResult, TraceEvent
from runai.tracing import TraceWriter

PNG = PNG_MAGIC + b"test-frame"
KIND = StepKind.accommodation


def test_png_ttl_purges_expired_captures_on_write(tmp_path):
    store = CaptureStore(tmp_path)
    store._write("mission1", KIND.value, PNG, [{"revision": 1}])
    old = store.frame_path("mission1", KIND.value, 1)
    expired = time.time() - 25 * 60 * 60
    os.utime(old, (expired, expired))
    store._write("mission1", KIND.value, PNG, [{"revision": 1}, {"revision": 2}])
    assert not old.exists()
    assert store.frame_path("mission1", KIND.value, 2).read_bytes() == PNG
    assert [entry["revision"] for entry in store.index("mission1", KIND.value)] == [2]


def test_png_purge_is_safe_for_empty_store(tmp_path):
    store = CaptureStore(tmp_path)
    store.purge()
    assert not store.root.exists()


def test_png_purge_logs_deletion_errors(tmp_path, monkeypatch, caplog):
    store = CaptureStore(tmp_path)
    store._write("mission1", KIND.value, PNG, [{"revision": 1}])
    path = store.frame_path("mission1", KIND.value, 1)
    os.utime(path, (0, 0))

    def denied(*args, **kwargs):
        raise PermissionError("deletion unavailable")

    monkeypatch.setattr(type(path), "unlink", denied)
    store.purge()
    assert path.exists()
    assert "Could not purge expired screenshot" in caplog.text


class FakeRun:
    live_view_url = None
    agent_view_url = None
    session_id = "test-session"
    browser_observation = None

    async def get_screenshot(self):
        return PNG


def client_for(store, run=None):
    service = SimpleNamespace(
        capture_store=store,
        get=lambda _: None,
        _capture_runs={("mission1", KIND): run} if run else {},
    )
    app = FastAPI()
    app.include_router(build_screenshot_router(service))
    return TestClient(app)


def test_record_persists_revisions_and_routes_survive_restart(tmp_path):
    async def scenario():
        service = MissionService(None, None, None, traces_dir=tmp_path)
        mission = Mission(id="mission1", query="test", steps={KIND: StepResult(kind=KIND)})
        service.missions[mission.id] = mission
        service._writers[mission.id] = TraceWriter(mission.id, tmp_path)
        run = FakeRun()
        service._runs[(mission.id, KIND)] = run
        for revision in range(1, 4):
            run.browser_observation = {"revision": revision, "url": "https://example.com", "title": "Example"}
            service._record(mission, TraceEvent(source="h", type="action", data={"step": KIND.value}))
            await asyncio.gather(*service.capture_store.tasks)
        service._record(mission, TraceEvent(source="h", type="action", data={"step": KIND.value}))
        assert not service.capture_store.tasks

    asyncio.run(scenario())
    store = CaptureStore(tmp_path)
    assert len(list((tmp_path / "screenshots/mission1/accommodation").glob("*.png"))) == 3
    with client_for(store) as client:
        entries = client.get("/api/missions/mission1/steps/accommodation/screenshots").json()
        assert [entry["revision"] for entry in entries] == [1, 2, 3]
        assert all(entry["title"] == "Example" and entry["at"] for entry in entries)
        assert client.get("/api/missions/mission1/steps/accommodation/screenshots/2.png").content == PNG
        assert client.get("/api/missions/missing/steps/accommodation/screenshots").json() == []
        for path in (
            "/api/missions/mission1/steps/invalid/screenshots",
            "/api/missions/mission1/steps/accommodation/screenshots/0.png",
            "/api/missions/mission1/steps/accommodation/screenshots/no.png",
            "/api/missions/%2E%2E/steps/accommodation/screenshots/1.png",
            "/api/missions/mission1/steps/accommodation/screenshots/99.png",
        ):
            assert client.get(path).status_code == 404
    (store.root / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        store.frame_path("escape", KIND.value, 1)


def test_cap_and_fetch_errors(tmp_path, caplog):
    async def scenario():
        store = CaptureStore(tmp_path)
        for revision in range(1, MAX_FRAMES + 4):
            store.schedule("mission1", KIND, {"revision": revision}, FakeRun())
        await asyncio.gather(*store.tasks)
        assert len(store.index("mission1", KIND.value)) == MAX_FRAMES
        assert len(list(store.directory("mission1", KIND.value).glob("*.png"))) == MAX_FRAMES
        assert ("mission1", KIND.value, MAX_FRAMES + 1) in store._seen
        store.schedule("mission1", KIND, {"revision": MAX_FRAMES + 1}, FakeRun())
        assert not store.tasks

        class BrokenRun:
            async def get_screenshot(self):
                raise RuntimeError("Fetch failed")

        class InvalidRun:
            async def get_screenshot(self):
                return b"not a PNG"

        for run in (BrokenRun(), InvalidRun()):
            store.schedule("bad", KIND, {"revision": len(caplog.records) + 1}, run)
            await asyncio.gather(*store.tasks)
        assert store.index("bad", KIND.value) == []

    asyncio.run(scenario())
    assert "Could not capture screenshot" in caplog.text


def test_capture_without_event_loop_is_safe(tmp_path, caplog):
    store = CaptureStore(tmp_path)
    store.schedule("mission1", KIND, {"revision": 1}, FakeRun())
    assert not store.tasks
    assert "without a running event loop" in caplog.text


@pytest.mark.parametrize("failure", [RuntimeError("Fetch failed"), TimeoutError(), b"invalid PNG", None])
def test_failed_capture_can_retry_same_revision(tmp_path, failure):
    async def scenario():
        class RetryRun(FakeRun):
            calls = 0

            async def get_screenshot(self):
                self.calls += 1
                if self.calls == 1:
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                return PNG

        store = CaptureStore(tmp_path)
        run = RetryRun()
        observation = {"revision": 1}
        store.schedule("mission1", KIND, observation, run)
        await asyncio.gather(*store.tasks)
        assert store.index("mission1", KIND.value) == []
        store.schedule("mission1", KIND, observation, run)
        await asyncio.gather(*store.tasks)
        assert run.calls == 2
        assert [entry["revision"] for entry in store.index("mission1", KIND.value)] == [1]

    asyncio.run(scenario())


def test_capture_drops_frame_when_revision_changes_during_fetch(tmp_path):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowRun(FakeRun):
            def __init__(self):
                self.browser_observation = {"revision": 1}

            async def get_screenshot(self):
                started.set()
                await release.wait()
                return PNG

        store = CaptureStore(tmp_path)
        run = SlowRun()
        store.schedule("mission1", KIND, run.browser_observation, run)
        await started.wait()
        run.browser_observation = {"revision": 2}
        release.set()
        await asyncio.gather(*store.tasks)
        assert store.index("mission1", KIND.value) == []
        assert not store.frame_path("mission1", KIND.value, 1).exists()
        store.schedule("mission1", KIND, run.browser_observation, run)
        await asyncio.gather(*store.tasks)
        assert [entry["revision"] for entry in store.index("mission1", KIND.value)] == [2]

    asyncio.run(scenario())


@pytest.mark.parametrize("inline", [False, True])
def test_replay_frames_and_existing_endpoint(tmp_path, inline):
    async def scenario():
        store = CaptureStore(tmp_path)
        for revision in (1, 2):
            store.schedule("mission1", KIND, {"revision": revision, "title": "Example"}, FakeRun())
            await asyncio.gather(*store.tasks)
        trace = ReplayTrace(label="Test", steps={KIND: ReplayStep(
            result=StepResult(kind=KIND),
            events=[TraceEvent(source="h", type="action", data={"step": KIND.value})],
        )})
        trace.attach_screenshots("mission1", tmp_path)
        path = tmp_path / "trace.json"
        trace.dump(path, inline=inline)
        trace = ReplayTrace.load(path)
        observations = []

        def on_event(event):
            if event.type == "browser_observation":
                observations.append(dict(run.browser_observation))

        async def ask(*args):
            return ""

        run = ReplayRun(trace, KIND, on_event, ask, 0)
        assert await run.get_screenshot() is None
        await run.wait()
        assert [o["revision"] for o in observations] == [1, 2]
        assert await run.get_screenshot() == PNG
        return run

    run = asyncio.run(scenario())
    with client_for(CaptureStore(tmp_path), run) as client:
        response = client.get("/api/missions/mission1/steps/accommodation/screenshot")
        assert response.status_code == 200
        assert response.content == PNG


@pytest.mark.parametrize("observation_type", ["AgentEvent.observation_event", "browser_observation"])
def test_replay_advances_frames_only_at_recorded_observations(observation_type):
    async def scenario():
        step = ReplayStep(
            result=StepResult(kind=KIND),
            events=[TraceEvent(source="h", type=event_type, message=str(index))
                    for index, event_type in enumerate(("navigation", observation_type, "navigation", observation_type))],
            screenshots=[{"revision": revision, "path": "unused.png"} for revision in (1, 2, 3)],
        )
        trace = ReplayTrace(label="Observation order", steps={KIND: step})
        recorded = []
        frames = []

        def on_event(event):
            revision = (run.browser_observation or {}).get("revision")
            if event.message is not None:
                recorded.append((event.message, revision))
            else:
                frames.append(revision)

        async def ask(*args):
            return ""

        run = ReplayRun(trace, KIND, on_event, ask, 0)
        await run.wait()
        assert recorded == [("0", None), ("1", 1), ("2", 1), ("3", 2)]
        assert frames == [1, 2, 3]

    asyncio.run(scenario())
