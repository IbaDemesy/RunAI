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
from runai.framing.engine import FramingEngine
from runai.framing.interpret import extract_slots
from runai.models import Source, StopPoint
from runai.safety import detect_stop_point


class Search:
    async def find_candidates(self, slots):
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
            FramingCreate(text="un semi-marathon à Lisbonne édition 2027")
        )
        assert session.slots[SlotName.city].value == "Lisbonne"
        assert session.slots[SlotName.distance_km].value == 21.0975
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, choice_id="edp")
        )
        assert session.selected_candidate_id == "edp" and session.open_questions
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                corrections={
                    SlotName.origin: "Nantes",
                    SlotName.budget: 500,
                    SlotName.nights: 2,
                    SlotName.transport_mode: "train",
                },
            ),
        )
        assert session.status == FramingStatus.ready_to_confirm, session.open_questions
        assert session.summary.race.distance_km == 21.097
        assert session.summary.race.name == "EDP Lisbon Half Marathon"

    asyncio.run(run())


def test_edition_and_year_extraction():
    assert extract_slots("un semi-marathon à Lisbonne édition 2027")[SlotName.city] == "Lisbonne"
    assert extract_slots("un marathon à Berlin en 2027")[SlotName.edition] == "2027"
    assert SlotName.edition not in extract_slots("un 10 km à Tokyo en juin 2028")


def test_negated_commitment_is_not_a_stop_point():
    assert detect_stop_point("Aucun paiement effectué, récapitulatif atteint") is None
    assert detect_stop_point("No payment was made") is None
    assert detect_stop_point("Page de paiement atteinte, aucun paiement effectué") is StopPoint.payment
    assert detect_stop_point("Proceed to payment") is StopPoint.payment
