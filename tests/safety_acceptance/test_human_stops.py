import asyncio
from unittest.mock import AsyncMock

import pytest

from runai.app.providers import (
    FORBIDDEN_HOSTS,
    registration_coverage,
    transport_coverage,
)
from runai.app.real import RealBrowserAgents
from runai.app.tasks import ASK_USER_RULES, STOP_RULES, TripBrief, build_task
from runai.contracts.common import Automation
from runai.contracts.mission import HumanAnswer, QuestionStatus
from runai.h.human_questions import HumanQuestionError, HumanQuestionRegistry
from runai.models import AgentQuestion, Race, RunnerProfile, StepKind, StopPoint
from runai.safety import STOP_INSTRUCTIONS, detect_stop_point, guard_task

STOPS = {
    StopPoint.payment: "payer",
    StopPoint.account_creation: "créer un compte",
    StopPoint.health_declaration: "déclaration de santé",
    StopPoint.consent: "j'accepte le règlement",
    StopPoint.submission: "confirmer l'inscription",
}


@pytest.mark.parametrize(
    "text", [*STOPS.values(), "réservation", "envoyer", "soumission"]
)
def test_yes_never_releases_human_stop(text):
    async def scenario():
        registry = HumanQuestionRegistry()
        registry.open(
            AgentQuestion(id="q", kind=StepKind.registration, question=text), "m1", 2
        )
        result = registry.answer(
            "q", "m1", HumanAnswer(answer="oui", revision=2, idempotency_key="answer-1")
        )
        assert result.status is QuestionStatus.refused
        assert registry.to_agent_question("q").answer is None
        with pytest.raises(HumanQuestionError, match="arrêt humain maintenu"):
            await registry.wait_answer("q")

    asyncio.run(scenario())


@pytest.mark.parametrize("stop,text", STOPS.items())
def test_every_stop_point_is_detected(stop, text):
    assert set(STOPS) == set(StopPoint)
    assert detect_stop_point(text) is stop


@pytest.mark.parametrize(
    "city,country", [("Tokyo", "JP"), ("Nairobi", "KE"), ("Lisbonne", "PT")]
)
@pytest.mark.parametrize(
    "kind", [StepKind.registration, StepKind.accommodation, StepKind.transport]
)
def test_generated_tasks_keep_all_guards_and_fictitious_profile(city, country, kind):
    race = Race(name=f"Course {city}", city=city, country=country)
    profile = RunnerProfile()
    brief = TripBrief(
        race_label=race.name,
        city=city,
        country=country,
        accommodation_site="site officiel Accor",
        transport_site="trenitalia.com",
    )
    task = build_task(kind, race, profile, brief=brief)
    assert task.endswith(STOP_INSTRUCTIONS)
    assert STOP_RULES in task and ASK_USER_RULES in task
    assert guard_task(task) == task
    assert "captcha" in task and "anti-bot protection" in task
    assert "BLOCKED: CAPTCHA/ANTI-BOT" in task
    if kind is StepKind.registration:
        assert "Fictitious profile" in task
        assert profile.email == "camille.test@example.com"
        assert profile.email in task and "Camille Test" in task
    assert "health data" not in task


@pytest.mark.parametrize("host", FORBIDDEN_HOSTS)
@pytest.mark.parametrize(
    "kind", [StepKind.registration, StepKind.accommodation, StepKind.transport]
)
def test_forbidden_platform_rejected_before_h_start(host, kind):
    runner = AsyncMock()
    agents = RealBrowserAgents(runner)
    url = f"https://www.{host}/race"
    race = Race(
        name="Course Nairobi", city="Nairobi", country="KE", registration_url=url
    )
    with pytest.raises(RuntimeError, match="rejected"):
        asyncio.run(
            agents.start(
                kind,
                "t",
                race,
                RunnerProfile(),
                lambda e: None,
                AsyncMock(),
                start_url=url,
            )
        )
    runner.start.assert_not_called()
    coverage = registration_coverage(race)
    assert coverage.automation is Automation.manual
    assert str(coverage.limitations[0].manual_url) == url


@pytest.mark.parametrize("url", [None, "https://race.example.org/register"])
def test_unknown_platform_is_explicitly_manual(url):
    official = "https://race.example.org/"
    coverage = registration_coverage(
        Race(name="Tokyo 10k", city="Tokyo", country="JP", registration_url=url),
        official,
    )
    assert coverage.automation in (Automation.manual, Automation.not_covered)
    assert str(coverage.limitations[0].manual_url) == (url or official)
    assert coverage.start_url is None


@pytest.mark.parametrize("country", ["JP", "KE", "PT"])
def test_uncovered_flight_is_manual_not_global_rejection(country):
    coverage = transport_coverage("avion", country)
    assert coverage.automation is Automation.manual
    assert coverage.limitations[0].code == "transport_not_covered"


def test_question_mission_revision_and_cancellation_isolation():
    registry = HumanQuestionRegistry()
    for mission in ("m1", "m2"):
        registry.open(
            AgentQuestion(id=mission, kind=StepKind.transport, question="Horaire ?"),
            mission,
            2,
        )
    answer = HumanAnswer(answer="matin", revision=2, idempotency_key="answer-1")
    with pytest.raises(HumanQuestionError, match="Mission ou révision"):
        registry.answer("m1", "m2", answer)
    with pytest.raises(HumanQuestionError, match="Mission ou révision"):
        registry.answer("m1", "m1", answer.model_copy(update={"revision": 1}))
    registry.cancel_mission("m1")
    with pytest.raises(HumanQuestionError, match="cancelled"):
        registry.answer("m1", "m1", answer)
    assert registry.get("m2").status is QuestionStatus.open
    assert registry.answer("m2", "m2", answer).status is QuestionStatus.answered
