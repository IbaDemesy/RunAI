"""Revue A : chaîne cadrage (A2) → confirmation → plan de lancement (A1), plusieurs villes."""

import asyncio
from datetime import date

import pytest

from runai.contracts.common import Automation, Provenance
from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingReply,
    FramingStatus,
    RaceCandidate,
)
from runai.contracts.mission import MissionSnapshot
from runai.framing.engine import FramingEngine
from runai.framing.launch import plan_launch
from runai.models import StepKind


class OneCandidate:
    def __init__(self, candidate):
        self.candidate = candidate

    async def find_candidates(self, slots, request_text: str | None = None):
        return [self.candidate]


def candidate(city, country, day, url, km=42.195):
    return RaceCandidate(
        id=city.lower(),
        name=f"Course de {city}",
        city=city,
        country=country,
        race_date=day,
        distances_km=[km],
        official_url=url,
        provenance=Provenance(kind="linkup", source_url=url),
    )


ANSWERS = {
    "distance_km": "42.195 km",
    "date_window": "mai 2027",
    "origin": "Dakar",
    "budget": "900",
    "nights": "2",
    "transport_mode": "avion",
}


@pytest.mark.parametrize(
    "text,cand,country",
    [
        (
            "une course à Nairobi",
            candidate("Nairobi", "KE", date(2027, 5, 30), "https://example.org/nbo"),
            "KE",
        ),
        (
            "un marathon à Tokyo",
            candidate("Tokyo", "JP", date(2027, 3, 7), "https://example.org/tyo"),
            "JP",
        ),
        (
            "un semi à Chicago depuis Montréal en avion 3 nuits 800 euros",
            candidate(
                "Chicago", "US", date(2027, 9, 26), "https://example.org/chi", 21.0975
            ),
            "US",
        ),
    ],
)
def test_framing_to_launch_plan_any_city(text, cand, country):
    plans = []

    async def on_confirm(session):
        plans.append(plan_launch(session))
        return MissionSnapshot.model_construct(mission_id=f"m-{session.id}")

    async def scenario():
        engine = FramingEngine(OneCandidate(cand))
        s = await engine.create(FramingCreate(text=text))
        asked = []
        while s.status is not FramingStatus.choosing_candidate:
            question = s.open_questions[0]
            asked.append(question.slots[0].value)
            s = await engine.reply(
                s.id,
                FramingReply(
                    revision=s.revision,
                    question_id=question.id,
                    text=ANSWERS[question.slots[0].value],
                ),
            )
        assert s.status is FramingStatus.choosing_candidate
        s = await engine.reply(
            s.id,
            FramingReply(
                revision=s.revision,
                question_id=s.open_questions[0].id,
                choice_id=cand.id,
            ),
        )
        while s.open_questions:
            question = s.open_questions[0]
            asked.append(question.slots[0].value)
            s = await engine.reply(
                s.id,
                FramingReply(
                    revision=s.revision,
                    question_id=question.id,
                    text=ANSWERS[question.slots[0].value],
                ),
            )
        assert s.status is FramingStatus.ready_to_confirm
        key = FramingConfirm(revision=s.revision, idempotency_key="review-a-key")
        first = await engine.confirm(s.id, key, on_confirm)
        again = await engine.confirm(s.id, key, on_confirm)
        assert first.mission_id == again.mission_id
        return asked

    asked = asyncio.run(scenario())
    assert len(plans) == 1
    plan = plans[0]
    assert plan.race.city == cand.city and plan.race.country == country
    assert plan.brief.race_date == cand.race_date
    assert "Paris" not in plan.brief.origin
    if "depuis" in text:
        assert "origin" not in asked and plan.brief.nights == 3
    assert plan.steps[StepKind.transport].automation is Automation.manual
    for step in plan.steps.values():
        assert (step.task is None) is (step.automation is not Automation.automated)
