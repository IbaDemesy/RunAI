import asyncio
import io
import wave
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import FakeBrowserAgents, FakeTranscriber
from runai.app.real import (
    RealAgentRun,
    RealBrowserAgents,
    RealRaceSearch,
    RealTranscriber,
)
from runai.app.server import build_service, create_app
from runai.models import Race, RunnerProfile, Source, StepKind, StepResult, StepStatus
from runai.search.models import RaceSheet


def test_real_race_search_adapts_linkup_sheet():
    sheet = RaceSheet(
        query="Marathon de Milan 2027",
        name="Wizz Air Milano Marathon",
        city="Milan",
        country="Italy",
        country_code="IT",
        race_date=date(2027, 4, 11),
        registration_url="https://in.njuko.com/milano-marathon",
        registration_verified=True,
        sources=[Source(url="https://www.milanomarathon.it", title="Official")],
    )
    search = RealRaceSearch(search=lambda query: sheet)

    race = asyncio.run(search.find_race("Marathon de Milan 2027"))

    assert race.name == "Wizz Air Milano Marathon"
    assert race.race_date == date(2027, 4, 11)
    assert str(race.registration_url) == "https://in.njuko.com/milano-marathon"
    assert race.sources[0].title == "Official"


def test_real_browser_agent_passes_registration_url_and_ask_tool():
    class FakeHRun:
        id = "h-session-1"
        agent_view_url = "https://platform.hcompany.ai/sessions/h-session-1"
        live_view_url = None

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.registration,
                status=StepStatus.stopped_before_commitment,
                summary="Stopped before payment.",
            )

    class FakeRunner:
        def __init__(self):
            self.params = None

        async def start(self, kind, task, **params):
            self.params = (kind, task, params)
            return FakeHRun()

    answers = []

    async def ask_user(question, options):
        answers.append((question, options))
        return options[0]

    runner = FakeRunner()
    agents = RealBrowserAgents(runner=runner, max_steps=12, max_time_s=60)
    race = Race(
        name="Wizz Air Milano Marathon",
        city="Milan",
        country="IT",
        race_date=date(2027, 4, 11),
        registration_url="https://in.njuko.com/milano-marathon",
    )
    run = asyncio.run(
        agents.start(
            StepKind.registration,
            "Prépare l'inscription.",
            race,
            RunnerProfile(),
            lambda event: None,
            ask_user,
            mission_id="mission-1",
        )
    )

    kind, task, params = runner.params
    answer = asyncio.run(
        params["tools"][0].fn(
            question="Quel sas ?", options=["moins de 3h30", "plus de 3h30"]
        )
    )
    assert kind is StepKind.registration
    assert "STOP" in task or "arrête" in task.lower()
    assert params["start_url"] == "https://in.njuko.com/milano-marathon"
    assert params["mission_id"] == "mission-1"
    assert params["max_steps"] == 12
    assert params["max_time_s"] == 60
    assert params["tools"][0].name == "ask_user"
    assert answer == "moins de 3h30"
    assert answers == [("Quel sas ?", ["moins de 3h30", "plus de 3h30"])]
    assert isinstance(run, RealAgentRun)
    assert run.session_id == "h-session-1"
    assert asyncio.run(run.wait()).status is StepStatus.stopped_before_commitment


def test_real_agent_run_extracts_exact_two_night_hotel_total():
    class HotelHRun:
        id = "hotel-session"
        agent_view_url = None
        live_view_url = None

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.accommodation,
                status=StepStatus.stopped_before_commitment,
                summary="PRIX_TOTAL_2_NUITS: 660,70 EUR",
            )

    result = asyncio.run(
        RealAgentRun(
            HotelHRun(), StepKind.accommodation, lambda event: None, timeout_s=10
        ).wait()
    )

    assert result.price_eur == 660.7
    assert result.status is StepStatus.stopped_before_commitment


def test_real_browser_rejects_non_njuko_registration_link():
    agents = RealBrowserAgents(runner=SimpleNamespace(), max_steps=1, max_time_s=1)
    race = Race(
        name="Wizz Air Milano Marathon",
        city="Milan",
        country="IT",
        registration_url="https://www.klikego.com/milano",
    )

    with pytest.raises(RuntimeError, match="Njuko"):
        asyncio.run(
            agents.start(
                StepKind.registration,
                "Prépare l'inscription.",
                race,
                RunnerProfile(),
                lambda event: None,
                lambda question, options: asyncio.sleep(0),
            )
        )


def test_real_agent_run_fails_without_a_detected_stop_point():
    class CompletedHRun:
        id = "h-session-2"
        agent_view_url = None
        live_view_url = None

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.transport,
                status=StepStatus.completed,
                summary="L'agent a simplement terminé.",
            )

    run = RealAgentRun(
        CompletedHRun(), StepKind.transport, lambda event: None, timeout_s=10
    )
    result = asyncio.run(run.wait())
    assert result.status is StepStatus.failed
    assert "point d'arrêt" in result.error


def test_real_transcriber_decodes_uploaded_wav_and_uses_voice_stream():
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 400)
    call = {}

    async def fake_streamer(chunks, *, sample_rate):
        call["sample_rate"] = sample_rate
        call["audio"] = b"".join([chunk async for chunk in chunks])
        yield SimpleNamespace(is_final=False, text="partiel")
        yield SimpleNamespace(is_final=True, text="Paris vers Milan")

    transcriber = RealTranscriber(streamer=fake_streamer)
    result = asyncio.run(transcriber.transcribe(audio.getvalue(), "audio/wav"))

    assert result == "Paris vers Milan"
    assert call == {"sample_rate": 16000, "audio": b"\0\0" * 400}


def test_service_selects_fakes_or_real_adapters_from_environment(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "fake-h-key")
    monkeypatch.setenv("LINKUP_API_KEY", "fake-linkup-key")
    monkeypatch.setenv("RUNAI_DEMO", "1")
    demo = build_service()
    assert demo.simulated
    assert isinstance(demo.agents, FakeBrowserAgents)
    assert isinstance(demo.transcriber, FakeTranscriber)

    monkeypatch.delenv("RUNAI_DEMO")
    real = build_service()
    assert not real.simulated
    assert isinstance(real.search, RealRaceSearch)
    assert isinstance(real.agents, RealBrowserAgents)
    assert isinstance(real.transcriber, FakeTranscriber)
    with TestClient(create_app(real)) as client:
        assert client.get("/api/health").json() == {
            "ok": True,
            "mode": "real",
            "simulated": False,
        }

    monkeypatch.setenv("GLADIA_API_KEY", "fake-gladia-key")
    real_with_voice = build_service()
    assert isinstance(real_with_voice.transcriber, RealTranscriber)

    monkeypatch.setenv("HAI_API_KEY", "")
    monkeypatch.setenv("HAI_API_KEY_2", "fake-secondary-h-key")
    monkeypatch.delenv("HAI_API_KEY_3", raising=False)
    secondary_only = build_service()
    assert not secondary_only.simulated
    assert isinstance(secondary_only.agents, RealBrowserAgents)
    with TestClient(create_app(secondary_only)) as client:
        assert client.get("/api/health").json() == {
            "ok": True,
            "mode": "real",
            "simulated": False,
        }

    monkeypatch.delenv("HAI_API_KEY_2")
    fallback = build_service()
    assert fallback.simulated
    assert isinstance(fallback.agents, FakeBrowserAgents)
