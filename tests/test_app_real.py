import asyncio
import io
import json
import wave
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import FakeTranscriber
from runai.app.providers import (
    LabeledBrowserAgents,
    UnavailableBrowserAgents,
    UnavailableTranscriber,
)
from runai.app.real import (
    LifecycleAgentRun,
    RealAgentRun,
    RealBrowserAgents,
    RealRaceSearch,
    RealTranscriber,
    lookup_official_info_tool,
)
from runai.app.server import build_service, create_app
from runai.h.answers import AccommodationAnswer, RegistrationAnswer
from runai.h.lifecycle import HAntiBotBlocked, HJob, HLifecycle, JobState
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


@pytest.mark.parametrize("typed_enabled", [True, False])
def test_real_browser_agent_passes_registration_url_and_ask_tool(monkeypatch, typed_enabled):
    monkeypatch.setenv("RUNAI_H_TYPED_ANSWERS", "1" if typed_enabled else "0")
    class FakeHRun:
        id = "h-session-1"
        agent_view_url = "https://platform.hcompany.ai/sessions/h-session-1"
        live_view_url = None
        status = "terminated"

        async def close(self):
            pass

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
    async def scenario():
        run = await agents.start(
            StepKind.registration, "Prépare l'inscription.", race, RunnerProfile(),
            lambda event: None, ask_user, mission_id="mission-1",
        )
        result = await run.wait()
        return run, result

    run, result = asyncio.run(scenario())

    kind, task, params = runner.params
    answer = asyncio.run(
        params["tools"][0].fn(
            question="Quel sas ?", options=["under 3h30", "plus de 3h30"]
        )
    )
    assert kind is StepKind.registration
    assert "stop" in task.lower()
    assert params["start_url"] == "https://in.njuko.com/milano-marathon"
    assert params["allowed_hosts"] == ("njuko.com", "in.njuko.com")
    assert params["mission_id"] == "mission-1"
    assert params["max_steps"] == 12
    assert params["max_time_s"] == 60
    assert params["answer_schema"] is (RegistrationAnswer if typed_enabled else None)
    assert params["tools"][0].name == "ask_user"
    assert [tool.name for tool in params["tools"]] == ["ask_user", "lookup_official_info"]
    assert "official site" in params["tools"][1].description
    assert answer == "under 3h30"
    assert answers == [("Quel sas ?", ["under 3h30", "plus de 3h30"])]
    assert isinstance(run, LifecycleAgentRun)
    assert run.session_id == "h-session-1"
    assert result.status is StepStatus.stopped_before_commitment


@pytest.mark.parametrize(
    "kind,brief,start_url,expected_hosts",
    [
        (StepKind.accommodation, SimpleNamespace(accommodation_url="https://all.accor.com"), "https://reservation.accor.com/room", ("all.accor.com", "accor.com", "reservation.accor.com")),
        (StepKind.transport, SimpleNamespace(transport_url="https://www.trenitalia.com"), "https://booking.trenitalia.com/train", ("trenitalia.com", "booking.trenitalia.com")),
        (StepKind.accommodation, None, "https://all.accor.com/hotel", ("all.accor.com", "accor.com")),
    ],
)
def test_real_browser_passes_step_platform_and_start_host(kind, brief, start_url, expected_hosts):
    class FakeRun:
        id = "hosts"
        status = "completed"
        live_view_url = None
        agent_view_url = None

        async def wait(self, **kwargs):
            return StepResult(kind=kind, status=StepStatus.stopped_before_commitment, price_eur=100)

        async def close(self):
            pass

    class FakeRunner:
        params = None

        async def start(self, step, task, **params):
            self.params = params
            return FakeRun()

    runner = FakeRunner()
    agents = RealBrowserAgents(runner=runner)

    async def scenario():
        run = await agents.start(
            kind, "Prepare travel", Race(name="Race", city="Rome", country="IT"),
            RunnerProfile(), lambda event: None, lambda q, o: asyncio.sleep(0),
            start_url=start_url, brief=brief,
        )
        assert (await run.wait()).status is StepStatus.stopped_before_commitment

    asyncio.run(scenario())
    assert runner.params["allowed_hosts"] == expected_hosts


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


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("total_field", ["total_price", "total_price_eur"])
def test_typed_hotel_report_precedes_legacy_price_and_stop(as_json, total_field):
    payload = {
        "stop_screen": "health", "hotel_name": "River Hotel", total_field: 180,
        "currency": "EUR", "summary": "Stopped before the health declaration.",
    }

    class Run:
        id = "typed-hotel"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.accommodation, status=StepStatus.completed,
                summary="PRIX_TOTAL_2_NUITS: 999 EUR", stop_point="payment",
                data={"answer": json.dumps(payload) if as_json else payload},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.accommodation, lambda e: None, 10).wait())
    assert result.price_eur == 180
    assert result.status is StepStatus.stopped_before_commitment
    assert result.stop_point == "health_declaration"
    assert result.data["answer_typed"]["hotel_name"] == "River Hotel"


def test_accommodation_start_keeps_canonical_answer_schema(monkeypatch):
    monkeypatch.delenv("RUNAI_H_TYPED_ANSWERS", raising=False)
    params = {}

    class Run:
        id = "canonical-schema"
        status = "completed"

        async def close(self):
            pass

        async def wait(self, **kwargs):
            return StepResult(kind=StepKind.accommodation, status=StepStatus.failed)

    class Runner:
        async def start(self, kind, task, **kwargs):
            params.update(kwargs)
            return Run()

    async def scenario():
        agents = RealBrowserAgents(runner=Runner())
        run = await agents.start(
            StepKind.accommodation, "Find a hotel.",
            Race(name="River Run", city="Lisbon", country="PT"), RunnerProfile(),
            lambda event: None, lambda question, options: asyncio.sleep(0),
        )
        await run.wait()

    asyncio.run(scenario())
    assert params["answer_schema"] is AccommodationAnswer


@pytest.mark.parametrize("data", [
    {"h_status": "failed"}, {"h_status": "completed", "off_platform": True},
    {"h_status": "completed", "error_code": "policy_refused"},
])
def test_real_typed_stop_cannot_mask_operational_failure(data):
    class Run:
        id = "failed-typed"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.transport, status=StepStatus.failed,
                error="Original operational failure", data={**data, "answer": {
                    "stop_screen": "none", "summary": "Done.",
                }},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.transport, lambda e: None, 10).wait())
    assert result.status is StepStatus.failed
    assert result.error == "Original operational failure"
    assert result.data["answer_typed"]["stop_screen"] == "none"


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
    assert "explicit stop" in result.error


@pytest.mark.parametrize("screen,expected", [
    ("payment", "payment"), ("account", "account_creation"),
    ("health", "health_declaration"), ("consent", "consent"),
    ("submission", "submission"), ("none", None), ("blocked", None),
])
def test_real_agent_uses_typed_answer(screen, expected):
    class Run:
        id = "typed-session"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.accommodation, status=StepStatus.completed,
                data={"answer": {
                    "stop_screen": screen, "total_price": 129, "currency": "EUR",
                    "final_url": "https://all.accor.com/x",
                    "options": [{"name": "Hotel", "total_price": 129}],
                }},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.accommodation, lambda e: None, 10).wait())
    assert result.price_eur == 129
    assert str(result.url) == "https://all.accor.com/x"
    assert result.stop_point == expected
    assert result.data["answer_typed"]["stop_screen"] == screen
    assert result.data["options"][0]["name"] == "Hotel"
    assert result.status is (
        StepStatus.failed if expected is None else StepStatus.stopped_before_commitment
    )
    if screen == "blocked":
        assert result.error == "Blocked by the site"


@pytest.mark.parametrize("currency", ["USD", None, "EUR"])
@pytest.mark.parametrize("fees", [None, 0, 5.5])
def test_registration_price_includes_displayed_fees(currency, fees):
    class Run:
        id = "registration-fees"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.registration, status=StepStatus.completed,
                data={"answer": {"stop_screen": "payment", "price": 50,
                                 "currency": currency, "fees": fees}},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.registration, lambda e: None, 10).wait())
    assert result.price_eur == (50 + (fees or 0) if currency == "EUR" else None)


@pytest.mark.parametrize("blocker", ["CAPTCHA challenge", "Anti-bot protection"])
def test_blocker_detail_preserves_lifecycle_anti_bot_classification(blocker):
    class Run:
        id = "blocked-session"
        status = "completed"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.transport, status=StepStatus.completed,
                data={"answer": {"stop_screen": "blocked", "blocker": blocker}},
            )

    run = Run()
    result = asyncio.run(RealAgentRun(run, StepKind.transport, lambda e: None, 10).wait())
    assert result.error.startswith(f"Blocked by the site: {blocker}")
    lifecycle = HLifecycle(SimpleNamespace())
    job = HJob(job_id="blocked-job", kind=StepKind.transport, mission_id=None)
    lifecycle._conclude(job, run, result)
    assert job.state is JobState.failed
    assert isinstance(job.error, HAntiBotBlocked)


@pytest.mark.parametrize("final_url,expected", [
    ("/checkout", "https://example.com/original"),
    ("ftp://example.com/file", "https://example.com/original"),
    ("not a URL", "https://example.com/original"),
    (None, "https://example.com/original"),
    ("https://example.com/checkout", "https://example.com/checkout"),
    ("http://example.com/checkout", "http://example.com/checkout"),
])
def test_typed_final_url_requires_absolute_http_url(final_url, expected):
    class Run:
        id = "final-url"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.transport, status=StepStatus.completed,
                url="https://example.com/original",
                data={"answer": {"stop_screen": "payment", "final_url": final_url}},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.transport, lambda e: None, 10).wait())
    assert str(result.url) == expected
    assert result.model_dump(mode="json")["url"] == expected


@pytest.mark.parametrize("currency", ["USD", None, "EUR"])
def test_typed_hotel_price_cannot_fall_back_to_summary(currency):
    class Run:
        id = "missing-price"

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.accommodation, status=StepStatus.completed,
                price_eur=999,
                data={"answer": {"stop_screen": "payment", "currency": currency,
                                 "summary": "PRIX_TOTAL_2_NUITS: 129 EUR"}},
            )

    result = asyncio.run(RealAgentRun(Run(), StepKind.accommodation, lambda e: None, 10).wait())
    assert result.price_eur is None
    assert result.status is StepStatus.failed
    if currency != "EUR":
        assert result.data["price_currency"] == currency


@pytest.mark.parametrize("data,error", [
    ({"error_code": "answer_validation"}, "Traceback"),
    ({}, "answer_validation: Traceback"),
    ({"error_code": None}, "answer_validation: Traceback"),
])
def test_answer_validation_has_readable_error(data, error):
    class Run:
        id = "invalid-answer"

        async def wait(self, **kwargs):
            return StepResult(kind=StepKind.transport, status=StepStatus.failed,
                              data=data, error=error)

    result = asyncio.run(RealAgentRun(Run(), StepKind.transport, lambda e: None, 10).wait())
    assert result.data["error_user"] == (
        "The agent finished but its report did not match the expected format."
    )


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


@pytest.mark.parametrize("frames", [0, 400, 4800])
def test_real_transcriber_paces_uploaded_audio_at_recording_rate(monkeypatch, frames):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * frames)
    elapsed = 0
    sent_at = []
    received = []

    async def sleep(delay):
        nonlocal elapsed
        elapsed += delay

    async def streamer(chunks, *, sample_rate):
        assert sample_rate == 16000
        async for chunk in chunks:
            sent_at.append(elapsed)
            received.append(chunk)
        yield SimpleNamespace(is_final=True, text="Une course" if received else "")

    monkeypatch.setattr("runai.voice.audio.asyncio.sleep", sleep)
    transcriber = RealTranscriber(streamer=streamer)
    if frames:
        assert asyncio.run(transcriber.transcribe(audio.getvalue(), "audio/wav")) == "Une course"
    else:
        with pytest.raises(RuntimeError, match="no final transcription"):
            asyncio.run(transcriber.transcribe(audio.getvalue(), "audio/wav"))
    assert b"".join(received) == b"\0\0" * frames
    assert sent_at == pytest.approx([0, .1, .2] if frames == 4800 else [0] if frames else [])


def test_service_selects_fakes_or_real_adapters_from_environment(monkeypatch):
    monkeypatch.delenv("RUNAI_MODE", raising=False)
    monkeypatch.setenv("RUNAI_DEMO", "1")
    demo = build_service()
    assert demo.simulated
    assert isinstance(demo.agents, LabeledBrowserAgents)
    assert isinstance(demo.transcriber, FakeTranscriber)

    monkeypatch.delenv("RUNAI_DEMO")
    monkeypatch.setenv("HAI_API_KEY", "fake-h-key")
    monkeypatch.setenv("LINKUP_API_KEY", "fake-linkup-key")
    monkeypatch.delenv("GLADIA_API_KEY", raising=False)
    real = build_service()
    assert not real.simulated
    assert isinstance(real.search, RealRaceSearch)
    assert isinstance(real.agents, RealBrowserAgents)
    assert isinstance(real.transcriber, UnavailableTranscriber)
    with TestClient(create_app(real)) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "live" and not health["simulated"]
        assert health["providers"]["gladia"] == "missing_key"

    monkeypatch.setenv("GLADIA_API_KEY", "fake-gladia-key")
    assert isinstance(build_service().transcriber, RealTranscriber)
    monkeypatch.setenv("HAI_API_KEY", "")
    monkeypatch.setenv("HAI_API_KEY_2", "fake-secondary-h-key")
    monkeypatch.delenv("HAI_API_KEY_3", raising=False)
    secondary_only = build_service()
    assert not secondary_only.simulated
    assert isinstance(secondary_only.agents, RealBrowserAgents)
    with TestClient(create_app(secondary_only)) as client:
        assert client.get("/api/health").json()["mode"] == "live"

    monkeypatch.delenv("HAI_API_KEY_2")
    unavailable = build_service()
    assert not unavailable.simulated
    assert isinstance(unavailable.agents, UnavailableBrowserAgents)


def test_real_agent_limits_default_to_sixty_steps_and_fifteen_minutes(monkeypatch):
    monkeypatch.delenv("RUNAI_H_MAX_STEPS", raising=False)
    monkeypatch.delenv("RUNAI_H_MAX_TIME_S", raising=False)

    agents = RealBrowserAgents(runner=SimpleNamespace())

    assert agents.max_steps == 60
    assert agents.max_time_s == 900


def test_real_question_timeout_is_capped_by_h_session_time(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "fake-h-key")
    monkeypatch.setenv("LINKUP_API_KEY", "fake-linkup-key")
    monkeypatch.delenv("RUNAI_DEMO", raising=False)
    monkeypatch.setenv("RUNAI_H_MAX_TIME_S", "200")
    monkeypatch.setenv("RUNAI_H_MAX_STEPS", "60")
    monkeypatch.setenv("RUNAI_QUESTION_TIMEOUT_S", "600")

    service = build_service()

    assert isinstance(service.agents, RealBrowserAgents)
    assert service.agents.max_time_s == 200
    assert service.question_timeout_s == 140


def test_real_agent_run_labels_live_provenance_and_reads_n_night_total():
    class HotelHRun:
        id = "hotel-4"
        agent_view_url = None
        live_view_url = None

        async def wait(self, **kwargs):
            return StepResult(
                kind=StepKind.accommodation,
                status=StepStatus.stopped_before_commitment,
                summary="PRIX_TOTAL_4_NUITS: 812,40 EUR",
            )

    result = asyncio.run(
        RealAgentRun(HotelHRun(), StepKind.accommodation, lambda event: None, timeout_s=10).wait()
    )
    assert result.price_eur == 812.4
    assert result.data["provenance"]["mode"] == "live"
    assert result.data["provenance"]["kind"] == "h_agent"
    assert "hotel-4" in result.data["provenance"]["label"]


def test_real_browser_refuses_forbidden_start_url_before_any_h_session():
    agents = RealBrowserAgents(runner=SimpleNamespace(), max_steps=1, max_time_s=1)
    race = Race(name="Course", city="Tokyo", country="JP")
    for url, name in (("https://www.booking.com/x", "Booking"), ("https://www.flytap.com", "TAP")):
        with pytest.raises(RuntimeError, match=name):
            asyncio.run(
                agents.start(
                    StepKind.accommodation, "t", race, RunnerProfile(),
                    lambda event: None, lambda q, o: asyncio.sleep(0), start_url=url,
                )
            )


class FakeAnswerClient:
    def __init__(self):
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return SimpleNamespace(
            answer="A PPS or an FFA licence is required.[1]",
            sources=[
                SimpleNamespace(
                    name="Health certificate",
                    url="https://www.milanomarathon.it/en/information/medical-certificate",
                    snippet="",
                )
            ],
        )


def test_lookup_official_info_tool_answers_from_official_domains_and_emits_event():
    class FakeRunner:
        params = None

        async def start(self, kind, task, **params):
            FakeRunner.params = params
            return SimpleNamespace(id="h-1", live_view_url=None)

    client = FakeAnswerClient()
    events = []
    agents = RealBrowserAgents(
        runner=FakeRunner(), max_steps=1, max_time_s=1, answer_client=lambda: client
    )
    race = Race(
        name="Wizz Air Milano Marathon",
        city="Milan",
        country="IT",
        registration_url="https://in.njuko.com/milano-marathon",
        sources=[
            Source(url="https://www.milanomarathon.it/en/", title="Official"),
            Source(url="https://www.ahotu.com/event/milano-marathon", title="Aggregator"),
        ],
    )

    async def scenario():
        await agents.start(
            StepKind.registration, "Prepare the registration.", race, RunnerProfile(),
            events.append, lambda q, o: asyncio.sleep(0),
        )
        await asyncio.sleep(0)
        lookup = next(t for t in FakeRunner.params["tools"] if t.name == "lookup_official_info")
        assert set(lookup.input_schema["properties"]) == {"question"}
        return await lookup.fn(question="Is a medical certificate required?")

    reply = asyncio.run(scenario())

    assert reply.startswith("A PPS or an FFA licence is required.[1]")
    assert "[1] https://www.milanomarathon.it/en/information/medical-certificate" in reply
    assert client.calls[0][1]["include_domains"] == ["milanomarathon.it", "in.njuko.com"]
    assert client.calls[0][1]["output_type"] == "sourcedAnswer"
    linkup_events = [e for e in events if e.source == "linkup"]
    assert len(linkup_events) == 1
    event = linkup_events[0]
    assert event.type == "linkup_answer"
    assert event.message == "Is a medical certificate required?"
    assert event.data["citations"] == [
        {
            "index": 1,
            "url": "https://www.milanomarathon.it/en/information/medical-certificate",
            "title": "Health certificate",
        }
    ]
    assert event.data["estimated_cost_usd"] > 0 and event.data["latency_s"] >= 0


def test_lookup_official_info_without_official_site_defers_to_the_user():
    events = []

    def no_client():
        raise AssertionError("Linkup must not be called without an official domain")

    lookup = lookup_official_info_tool(
        Race(name="Unknown 10K", city="", country=""), events.append, no_client
    )
    reply = asyncio.run(lookup.fn(question="Cut-off time?"))

    assert "ask_user" in reply
    assert events == []


def test_lookup_official_info_reports_linkup_failures_as_text():
    def broken_client():
        raise RuntimeError("LINKUP_API_KEY missing")

    lookup = lookup_official_info_tool(
        Race(name="Course", city="", country="", sources=[Source(url="https://race.example.org")]),
        lambda event: None,
        broken_client,
    )

    assert "ask_user" in asyncio.run(lookup.fn(question="Fees?"))
