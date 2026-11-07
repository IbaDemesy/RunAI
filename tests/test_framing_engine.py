import asyncio
from datetime import date

import pytest

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingError,
    FramingReply,
    FramingStatus,
    RaceCandidate,
    SlotName,
)
from runai.contracts.mission import MissionSnapshot
from runai.framing.engine import FramingEngine
from runai.framing.interpret import extract_slots
from runai.models import Source


class Search:
    def __init__(self, count=0, fail=False, close_match=False, distances=(10,)):
        self.count = count
        self.fail = fail
        self.close_match = close_match
        self.distances = distances
        self.calls = []

    async def find_candidates(self, slots):
        self.calls.append(slots)
        if self.fail:
            raise RuntimeError("Service indisponible")
        return [
            RaceCandidate(
                id=f"c{i}",
                name=f"Course {i}",
                city=slots[SlotName.city].value,
                country="",
                race_date=date(2028, 6, 12),
                distances_km=list(self.distances),
                sources=[Source(url="https://example.org/race")],
                provenance=Provenance(kind="fixture", url="https://example.org/race"),
                limitations=[
                    Limitation(
                        code="close_match",
                        message="Proche de votre demande, pas exactement ce que vous avez demandé.",
                    )
                ]
                if self.close_match
                else [],
            )
            for i in range(self.count)
        ]


def mission(session):
    return MissionSnapshot(
        mission_id="m1",
        framing_id=session.id,
        framing_revision=session.revision,
        mode=session.mode,
        status="running",
        sequence=0,
        steps=[],
    )


async def ready(engine):
    session = await engine.create(
        FramingCreate(
            text="Une course à Tokyo depuis Lyon, 800 euros, 2 nuits, en avion"
        )
    )
    return await engine.reply(
        session.id, FramingReply(revision=session.revision, choice_id="c0")
    )


@pytest.mark.parametrize(
    "city", ["Lisbonne", "Tokyo", "Nairobi", "Chicago", "São Paulo", "Valence"]
)
def test_vague_any_city(city):
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text=f"une course à {city}"))
        assert {k: s.value for k, s in session.slots.items() if s.is_known} == {
            SlotName.city: city
        }
        assert session.open_questions and session.summary is None
        assert SlotName.city not in {s for q in session.open_questions for s in q.slots}

    asyncio.run(run())


def test_extraction_explicit_only():
    assert extract_slots("une course") == {}
    assert SlotName.distance_km not in extract_slots("pas de marathon")
    assert SlotName.city not in extract_slots("une course à Tokyo ou Nairobi")
    assert extract_slots(
        "marathon de Nairobi depuis São Paulo le 12 avril 2027, 1200 €, 3 nuits, train"
    ) == {
        SlotName.city: "Nairobi",
        SlotName.origin: "São Paulo",
        SlotName.race_date: "2027-04-12",
        SlotName.distance_km: 42.195,
        SlotName.budget: 1200,
        SlotName.nights: 3,
        SlotName.transport_mode: "train",
    }
    assert (
        extract_slots("semi à Tokyo en avril 2028")[SlotName.date_window]
        == "avril 2028"
    )
    assert SlotName.race_date not in extract_slots("course le 31 février 2028")
    assert (
        extract_slots("race in Chicago from Boston, 10 km, no budget")[SlotName.origin]
        == "Boston"
    )


def test_named_race_capture_and_numeric_location_boundary():
    templiers = extract_slots("le trail des Templiers à Millau")
    assert templiers[SlotName.race] == "trail des Templiers"
    assert templiers[SlotName.city] == "Millau"

    ecotrail = extract_slots("Ecotrail Paris 45 km")
    assert ecotrail[SlotName.race] == "Ecotrail Paris"
    assert SlotName.city not in ecotrail
    assert ecotrail[SlotName.distance_km] == 45

    lausanne = extract_slots("une course de 20 km à Lausanne")
    assert lausanne[SlotName.city] == "Lausanne"
    assert lausanne[SlotName.distance_km] == 20

    origin = extract_slots("course à Tokyo depuis 20 km de Lyon")
    assert SlotName.origin not in origin


@pytest.mark.parametrize(
    ("text", "city", "distance"),
    [
        ("marathon de Paris", "Paris", 42.195),
        ("semi-marathon de Bordeaux", "Bordeaux", 21.0975),
        ("un 10 km à Nantes", "Nantes", 10),
    ],
)
def test_generic_race_forms_do_not_become_named_race(text, city, distance):
    values = extract_slots(text)
    assert values[SlotName.city] == city
    assert values[SlotName.distance_km] == distance
    assert SlotName.race not in values


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("course à Tokyo en mars", "mars 2027"),
        ("course à Tokyo en novembre", "novembre 2026"),
        ("course à Tokyo au mois de mai", "mai 2027"),
    ],
)
def test_month_without_year_uses_next_occurrence(text, expected):
    assert extract_slots(text, today=date(2026, 11, 7))[SlotName.date_window] == expected


def test_month_window_uses_explicit_edition_year():
    values = extract_slots(
        "course à Tokyo en mars édition 2030", today=date(2026, 11, 7)
    )
    assert values[SlotName.date_window] == "mars 2030"
    assert values[SlotName.edition] == "2030"


def test_candidates_selection_and_channel_parity():
    async def run():
        states = []
        for channel in ("text", "voice"):
            engine = FramingEngine(Search(2), DataMode.demo)
            session = await engine.create(
                FramingCreate(text="une course à Chicago", channel=channel)
            )
            assert session.status == FramingStatus.choosing_candidate
            assert session.slots[SlotName.race].value is None
            assert len(session.open_questions[0].choices) == 3
            assert session.open_questions[0].text == (
                "Quel événement souhaitez-vous ? Vérifiez les sources et l'édition."
            )
            session = await engine.reply(
                session.id, FramingReply(revision=1, choice_id="c1", channel=channel)
            )
            assert session.selected_candidate_id == "c1"
            assert session.slots[SlotName.distance_km].value == 10
            assert session.turns[-1].channel == channel
            states.append({k: s.value for k, s in session.slots.items()})
        assert states[0] == states[1]

    asyncio.run(run())


def test_close_candidates_use_close_match_choice_copy():
    async def run():
        session = await FramingEngine(
            Search(2, close_match=True), DataMode.demo
        ).create(FramingCreate(text="course à Tokyo"))
        question = session.open_questions[0]
        assert question.text == (
            "Je n'ai pas trouvé exactement votre course. Voici les plus proches — "
            "laquelle vous intéresse ?"
        )
        assert question.choices[0].label == (
            "Course 0 — 2028-06-12 · proche de votre demande"
        )
        assert question.choices[-1].id == "none"
        assert question.choices[-1].label == "Aucune, je précise"

    asyncio.run(run())


def test_close_match_distance_selection_uses_only_available_distance_or_asks():
    async def run():
        requested = "une course à Tokyo, 21.1 km"
        engine = FramingEngine(
            Search(1, close_match=True, distances=[10]), DataMode.demo
        )
        single = await engine.create(FramingCreate(text=requested))
        single = await engine.reply(
            single.id, FramingReply(revision=single.revision, choice_id="c0")
        )
        assert single.slots[SlotName.distance_km].value == 10

        multiple_engine = FramingEngine(
            Search(1, close_match=True, distances=[10, 21]), DataMode.demo
        )
        multiple = await multiple_engine.create(
            FramingCreate(text="une course à Tokyo, 42.195 km")
        )
        multiple = await multiple_engine.reply(
            multiple.id,
            FramingReply(revision=multiple.revision, choice_id="c0"),
        )
        assert not multiple.slots[SlotName.distance_km].is_known
        assert any(
            question.slots == [SlotName.distance_km]
            for question in multiple.open_questions
        )

    asyncio.run(run())


def test_no_candidates_message_explains_that_search_was_expanded():
    async def run():
        session = await FramingEngine(Search(), DataMode.demo).create(
            FramingCreate(text="course à Tokyo")
        )
        limitation = next(
            limitation
            for limitation in session.limitations
            if limitation.code == "no_candidates"
        )
        assert limitation.message == (
            "Je n'ai trouvé aucune course correspondante, même en élargissant. "
            "Donnez le nom officiel de la course ou le lien de son site."
        )

    asyncio.run(run())


def test_correction_confirmation_idempotency_and_cancel():
    async def run():
        engine = FramingEngine(Search(1), DataMode.demo)
        session = await ready(engine)
        assert session.status == FramingStatus.ready_to_confirm
        assert session.summary.date_range == (date(2028, 6, 11), date(2028, 6, 13))
        old_revision = session.revision
        session = await engine.reply(
            session.id, FramingReply(revision=old_revision, text="budget 900 euros")
        )
        assert session.revision == old_revision + 1
        assert session.summary.budget_eur == 900
        calls = []

        async def launch(s):
            calls.append(s)
            assert s.status == FramingStatus.confirmed
            await asyncio.sleep(0)
            return mission(s)

        with pytest.raises(FramingError):
            await engine.confirm(
                session.id,
                FramingConfirm(revision=old_revision, idempotency_key="same-key"),
                launch,
            )
        request = FramingConfirm(revision=session.revision, idempotency_key="same-key")
        results = await asyncio.gather(
            engine.confirm(session.id, request, launch),
            engine.confirm(session.id, request, launch),
        )
        assert results[0] == results[1] and len(calls) == 1
        with pytest.raises(FramingError):
            await engine.confirm(
                session.id,
                request.model_copy(update={"idempotency_key": "other-key"}),
                launch,
            )
        other = await ready(engine)
        await engine.cancel(other.id)
        with pytest.raises(FramingError):
            await engine.confirm(
                other.id,
                FramingConfirm(revision=other.revision, idempotency_key="cancel-key"),
                launch,
            )
        assert len(calls) == 1

    asyncio.run(run())


def test_manual_answers_stale_empty_and_errors():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text="Je cherche une course"))
        assert not any(s.is_known for s in session.slots.values())
        city_question = next(
            q for q in session.open_questions if q.slots == [SlotName.city]
        )
        session = await engine.reply(
            session.id,
            FramingReply(revision=1, question_id=city_question.id, text="Nairobi"),
        )
        with pytest.raises(FramingError):
            await engine.reply(session.id, FramingReply(revision=1, text="Tokyo"))
        with pytest.raises(FramingError):
            await engine.reply(session.id, FramingReply(revision=2))
        with pytest.raises(FramingError):
            await engine.reply(
                session.id, FramingReply(revision=2, corrections={SlotName.nights: -1})
            )
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=2,
                corrections={
                    SlotName.race: "Course officielle",
                    SlotName.race_date: "2028-06-12",
                    SlotName.distance_km: 10,
                    SlotName.origin: "Mombasa",
                    SlotName.budget: None,
                    SlotName.nights: 0,
                    SlotName.transport_mode: "bus",
                },
            ),
        )
        assert session.summary.race.country == ""
        assert session.summary.date_range == (date(2028, 6, 12),) * 2

        async def fail(s):
            raise RuntimeError("Impossible de lancer")

        with pytest.raises(RuntimeError):
            await engine.confirm(
                session.id, FramingConfirm(revision=3, idempotency_key="fail-key"), fail
            )
        assert engine.get(session.id).status == FramingStatus.ready_to_confirm
        with pytest.raises(RuntimeError, match="Service indisponible"):
            await FramingEngine(Search(fail=True)).create(
                FramingCreate(text="course à Tokyo")
            )

    asyncio.run(run())


def test_candidate_rejection_and_correction_preserve_known_answers():
    async def run():
        search = Search(2)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(text="course à Nairobi depuis Mombasa")
        )
        session = await engine.reply(
            session.id, FramingReply(revision=1, choice_id="none")
        )
        assert session.status == FramingStatus.collecting
        session = await engine.reply(
            session.id, FramingReply(revision=2, text="2 nuits")
        )
        assert len(search.calls) == 1
        assert not session.candidates
        assert not any(SlotName.origin in q.slots for q in session.open_questions)
        selected = await ready(engine)
        selected = await engine.reply(
            selected.id,
            FramingReply(
                revision=selected.revision,
                corrections={SlotName.race_date: "2028-07-12"},
            ),
        )
        assert selected.status == FramingStatus.choosing_candidate
        assert selected.slots[SlotName.city].value == "Tokyo"
        assert selected.slots[SlotName.origin].value == "Lyon"

    asyncio.run(run())


def test_french_conjunction_car_is_not_a_transport_mode():
    assert SlotName.transport_mode not in extract_slots(
        "je viens car je veux courir à Tokyo"
    )
    assert extract_slots("j'y vais en voiture")[SlotName.transport_mode] == "car"
