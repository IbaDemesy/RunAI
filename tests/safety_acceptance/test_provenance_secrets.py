import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runai.app.providers import ProviderUnavailableError, build_providers
from runai.app.replay import ReplayBrowserAgents, ReplayTrace
from runai.contracts.common import DataMode
from runai.contracts.mission import EventEnvelope, MissionSnapshot
from runai.h.lifecycle import HKeyMissing, HLifecycle, HLifecycleError
from runai.models import RunnerProfile, StepKind, StepResult, StepStatus

SENTINEL = "sk-SENTINEL-E2-123"


def snapshot(**changes):
    return MissionSnapshot(
        mission_id="m1",
        framing_id="f1",
        framing_revision=1,
        mode=DataMode.live,
        status="failed",
        sequence=0,
        steps=[],
        **changes,
    )


@pytest.mark.parametrize("provider", ["h", "linkup", "gladia"])
def test_live_without_key_is_error_never_fake(provider):
    providers = build_providers(env={})
    assert providers.mode is DataMode.live and not providers.simulated
    assert providers.health_payload()["providers"][provider] == "missing_key"
    calls = {
        "h": lambda: providers.agents.start(StepKind.transport, "t"),
        "linkup": lambda: providers.search.find_race("course à Tokyo"),
        "gladia": lambda: providers.transcriber.transcribe(b"", "audio/wav"),
    }
    with pytest.raises(ProviderUnavailableError, match="Live mode"):
        asyncio.run(calls[provider]())
    with pytest.raises(HKeyMissing):
        HLifecycle.from_env()


def test_environment_keys_are_not_implicitly_serialized(monkeypatch, tmp_path):
    for name in (
        "HAI_API_KEY", "HAI_API_KEY_2", "LINKUP_API_KEY", "LINKUP_API_KEY_2",
        "GLADIA_API_KEY", "GLADIA_API_KEY_2",
    ):
        monkeypatch.setenv(name, SENTINEL)
    health = build_providers(DataMode.demo).health_payload()
    mission = snapshot()
    event = EventEnvelope.build("m1", 0, "snapshot", mission.model_dump(mode="json"))
    trace = ReplayTrace.from_mission_snapshot({"id": "m1", "steps": []})
    path = tmp_path / "trace.json"
    trace.dump(path)
    lifecycle = HLifecycle(
        SimpleNamespace(
            accounts=[SimpleNamespace(name="HAI_API_KEY", active=0, max_concurrency=1)]
        )
    )
    for output in (
        json.dumps(health),
        mission.model_dump_json(),
        event.to_sse(),
        path.read_text(),
        json.dumps(lifecycle.slots()),
    ):
        assert SENTINEL not in output


@pytest.mark.parametrize("surface", ["snapshot", "sse", "replay"])
def test_provider_echoed_key_is_redacted(surface, monkeypatch, tmp_path):
    monkeypatch.setenv("HAI_API_KEY", SENTINEL)
    step = StepResult(kind=StepKind.transport, error=f"provider error: {SENTINEL}")
    mission = snapshot(error=f"provider error: {SENTINEL}")
    mission.steps.append(step)
    if surface == "snapshot":
        output = mission.model_dump_json()
    elif surface == "sse":
        output = EventEnvelope.build("m1", 1, "error", {"message": step.error}).to_sse()
    else:
        trace = ReplayTrace.from_mission_snapshot(
            {"id": "m1", "steps": [step.model_dump(mode="json")]}
        )
        path = tmp_path / "trace.json"
        trace.dump(path)
        output = path.read_text()
    assert SENTINEL not in output


def test_lifecycle_exception_does_not_echo_key(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", SENTINEL)

    async def scenario():
        runner = SimpleNamespace(
            start=AsyncMock(side_effect=RuntimeError(f"Authorization: {SENTINEL}")),
            accounts=[],
        )
        lifecycle = HLifecycle(runner)
        job = lifecycle.submit(StepKind.transport, "t", mission_id="m1")
        with pytest.raises(HLifecycleError) as error:
            await job.wait()
        assert SENTINEL not in str(error.value)
        runner.start.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("city", ["Tokyo", "Nairobi", "Lisbonne"])
def test_replay_of_live_result_never_exposes_live_view(city):
    async def scenario():
        trace = ReplayTrace.from_mission_snapshot(
            {
                "id": city,
                "steps": [
                    {
                        "kind": "transport",
                        "status": "stopped_before_commitment",
                        "h_session_id": "real-h-id",
                        "live_view_url": "https://example.org/live",
                        "data": {"provenance": {"mode": "live", "kind": "h_agent"}},
                    }
                ],
            }
        )
        agents = ReplayBrowserAgents(trace)
        run = await agents.start(
            StepKind.transport, "t", None, RunnerProfile(), lambda e: None, AsyncMock()
        )
        result = await run.wait()
        assert run.live_view_url is None and result.live_view_url is None
        assert result.data["provenance"]["mode"] == "replay"
        assert result.data["provenance"]["kind"] == "replay"
        assert result.status is StepStatus.stopped_before_commitment
        absent = await agents.start(
            StepKind.registration,
            "t",
            None,
            RunnerProfile(),
            lambda e: None,
            AsyncMock(),
        )
        assert (await absent.wait()).status is StepStatus.failed

    asyncio.run(scenario())
