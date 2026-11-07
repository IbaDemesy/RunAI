import asyncio
from datetime import date

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    FramingStatus,
    RaceCandidate,
    SlotName,
    matching_distance,
)
from runai.contracts.mission import HumanAnswer, QuestionStatus
from runai.framing.engine import FramingEngine
from runai.framing.interpret import extract_slots
from runai.h.human_questions import HumanQuestionRegistry
from runai.h.runner import build_step_result
from runai.models import AgentQuestion, Source, StepKind, StopPoint
from runai.safety import detect_stop_point


class Search:
    async def find_candidates(self, slots, request_text: str | None = None):
        return [
            RaceCandidate(
                id="edp",
                name="EDP Lisbon Half Marathon",
                city="Lisbonne",
                country="PT",
                race_date=date(2027, 3, 7),
                distances_km=[21.097, 10.0],
                sources=[Source(url="https://maratonaclubedeportugal.com/en/")],
                provenance=Provenance(kind="fixture", url="https://maratonaclubedeportugal.com/en/"),
            )
        ]


def test_matching_distance_tolerates_rounding_only():
    assert matching_distance([21.097, 10.0], 21.0975) == 21.097
    assert matching_distance([42.2], 42.195) == 42.2
    assert matching_distance([10.0], 21.0975) is None


def test_rounded_official_distance_is_selectable_until_summary():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "un semi-marathon à Lisbonne en mars 2027 depuis Nantes, "
                    "500 euros, 2 nuits, train"
                )
            )
        )
        assert session.slots[SlotName.city].value == "Lisbonne"
        assert session.slots[SlotName.distance_km].value == 21.0975
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, choice_id="edp")
        )
        assert session.selected_candidate_id == "edp"
        assert session.status == FramingStatus.ready_to_confirm
        assert session.summary.race.distance_km == 21.097
        assert session.summary.race.name == "EDP Lisbon Half Marathon"

    asyncio.run(run())


def test_edition_and_year_extraction():
    assert extract_slots("un semi-marathon à Lisbonne édition 2027")[SlotName.city] == "Lisbonne"
    assert extract_slots("un marathon à Berlin en 2027")[SlotName.edition] == "2027"
    assert SlotName.edition not in extract_slots("un 10 km à Tokyo en juin 2028")


def test_negated_commitment_is_not_a_reported_stop_point():
    def report(text):
        return detect_stop_point(text, ignore_negated=True)

    assert report("Aucun paiement effectué, récapitulatif atteint") is None
    assert report("No payment was made") is None
    assert report("Page de paiement atteinte, aucun paiement effectué") is StopPoint.payment
    assert report("Proceed to payment") is StopPoint.payment
    assert build_step_result(StepKind.registration, "completed", answer="Aucun paiement effectué").stop_point is None


def test_guards_stay_strict_on_negations():
    assert detect_stop_point("No payment yes pay") is StopPoint.payment
    registry = HumanQuestionRegistry()
    registry.open(
        AgentQuestion(id="q1", kind=StepKind.registration, question="No payment", options=[]),
        "m1",
        1,
    )
    answered = registry.answer("q1", "m1", HumanAnswer(answer="pay", revision=1, idempotency_key="key-0001"))
    assert answered.status == QuestionStatus.refused and answered.answer is None
