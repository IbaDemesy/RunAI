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
from runai.framing.interpret import extract_slots, normalize_date_window
from runai.models import Source
from runai.search.candidates import CandidateSearchError


class Search:
    def __init__(self, count=0, fail=False, close_match=False, distances=(10,)):
        self.count = count
        self.fail = fail
        self.close_match = close_match
        self.distances = distances
        self.calls = []

    async def find_candidates(self, slots, request_text: str | None = None):
        self.calls.append(slots)
        if self.fail:
            raise RuntimeError("Service unavailable")
        return [
            RaceCandidate(
                id=f"c{i}",
                name=f"Race {i}",
                city=slots[SlotName.city].value,
                country="",
                race_date=date(2028, 6, 12),
                distances_km=list(self.distances),
                sources=[Source(url="https://example.org/race")],
                provenance=Provenance(kind="fixture", url="https://example.org/race"),
                limitations=[
                    Limitation(
                        code="close_match",
                        message="Close to your request, not an exact match.",
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
            text=(
                "Une course à Tokyo, 10 km, en juin 2028, depuis Lyon, "
                "800 euros, 2 nuits, en avion"
            )
        )
    )
    return await engine.reply(
        session.id, FramingReply(revision=session.revision, choice_id="c0")
    )


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["en fait plutôt Porto", "actually Porto", "rather Porto", "instead Porto"])
async def test_place_correction_does_not_answer_origin(text):
    engine = FramingEngine(Search(), DataMode.demo)
    session = await engine.create(FramingCreate(text="I want a half marathon in Lisbon in March 2027"))
    question = next(q for q in session.open_questions if q.slots == [SlotName.origin])
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, question_id=question.id, text=text,
    ))
    assert session.slots[SlotName.city].value == "Porto"
    assert not session.slots[SlotName.origin].is_known
    assert any(q.slots == [SlotName.origin] for q in session.open_questions)


@pytest.mark.anyio
@pytest.mark.parametrize("answer", ["je sais pas encore", "oui", "non", "peu importe", "no", "none", "I don't know", "not sure", "1", "x" * 81])
async def test_nonanswer_keeps_city_question_open_with_clarification(answer):
    engine = FramingEngine(Search(), DataMode.demo)
    session = await engine.create(FramingCreate(text="I want a race"))
    question = next(q for q in session.open_questions if q.slots == [SlotName.city])
    old_revision = session.revision
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, question_id=question.id, text=answer,
    ))
    assert not session.slots[SlotName.city].is_known
    assert any(q.slots == [SlotName.city] for q in session.open_questions)
    assert session.revision == old_revision + 1
    assert session.turns[-1].role == "assistant"
    assert "Please" in session.turns[-1].text


@pytest.mark.anyio
async def test_candidate_text_never_becomes_manual_race():
    engine = FramingEngine(Search(2), DataMode.demo)
    session = await engine.create(FramingCreate(text=(
        "Une course à Tokyo, 10 km, en juin 2028, depuis Lyon, 800 euros, 2 nuits, en avion"
    )))
    question = next(q for q in session.open_questions if q.choices)
    for answer in ["the sunday one please", "None of these"]:
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, question_id=question.id, text=answer,
        ))
        assert not session.slots[SlotName.race].is_known
        assert session.status != FramingStatus.ready_to_confirm
        assert session.summary is None
        assert session.open_questions
        assert session.turns[-1].role == "assistant"


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Milan marathon in April 2027 from London",
            {SlotName.city: "Milan", SlotName.origin: "London",
             SlotName.date_window: "April 2027", SlotName.distance_km: 42.195},
        ),
        (
            "Tokyo 10K from London",
            {SlotName.city: "Tokyo", SlotName.origin: "London", SlotName.distance_km: 10},
        ),
        (
            "marathon de Milan en avril 2027 depuis Londres",
            {SlotName.city: "Milan", SlotName.origin: "Londres",
             SlotName.date_window: "April 2027", SlotName.distance_km: 42.195},
        ),
        (
            "course de 10 km à Tokyo depuis Londres",
            {SlotName.city: "Tokyo", SlotName.origin: "Londres", SlotName.distance_km: 10},
        ),
        (
            "half in New York in Apr 2027 from São Paulo",
            {SlotName.city: "New York", SlotName.origin: "São Paulo",
             SlotName.date_window: "April 2027", SlotName.distance_km: 21.0975},
        ),
    ],
)
def test_bilingual_city_first_and_date_extraction(text, expected):
    actual = extract_slots(text)
    if SlotName.date_window in actual:
        actual[SlotName.date_window] = normalize_date_window(actual[SlotName.date_window])
    for slot, value in expected.items():
        assert actual[slot] == value


@pytest.mark.parametrize(
    "text", ["in April 2027", "in Apr. 2027", "en avril 2027", "in December", "in 2027"]
)
def test_dates_never_become_race_cities(text):
    assert SlotName.city not in extract_slots(text)


@pytest.mark.parametrize(
    ("month", "english"),
    list(zip(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
        strict=True,
    )),
)
def test_english_month_names_and_abbreviations(month, english):
    assert normalize_date_window(extract_slots(f"race in {month} 2028")[SlotName.date_window]) == f"{english} 2028"
    assert normalize_date_window(extract_slots(f"race in {english} 2028")[SlotName.date_window]) == f"{english} 2028"


@pytest.mark.parametrize("distance", ["10K", "10k", "10 km"])
def test_english_numeric_distances(distance):
    assert extract_slots(distance)[SlotName.distance_km] == 10


@pytest.mark.parametrize("distance", ["half marathon", "half-marathon", "half"])
def test_english_half_marathon_distances(distance):
    assert extract_slots(distance)[SlotName.distance_km] == 21.0975


def test_english_edition_and_month_without_year():
    values = extract_slots("Tokyo half in April edition 2027", today=date(2026, 11, 7))
    assert normalize_date_window(values[SlotName.date_window]) == "April 2027"
    assert values[SlotName.edition] == "2027"


@pytest.mark.parametrize("text", ["12 April 2027", "April 12, 2027", "Apr 12 2027"])
def test_english_full_dates(text):
    assert extract_slots(text)[SlotName.race_date] == "2027-04-12"


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
    named_marathon = extract_slots(
        "Marathon de Paris depuis Lyon en train, 2 nuits, 300 euros"
    )
    assert named_marathon[SlotName.race] == "Marathon de Paris"
    named_new_york = extract_slots("Marathon de New York depuis Paris")
    assert named_new_york[SlotName.race] == "Marathon de New York"


def test_candidate_search_waits_for_date_and_logistics_answers():
    async def run():
        search = Search(1)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(text="Un semi marathon à Pékin")
        )
        assert search.calls == []
        assert [q.slots for q in session.open_questions] == [
            [SlotName.date_window],
            [SlotName.origin],
            [SlotName.budget],
            [SlotName.nights],
            [SlotName.transport_mode],
        ]
        assert session.open_questions[0].text == (
            "Which period (month or season)? Say 'any time' if you are flexible."
        )

        answers = ("en avril", "depuis Paris", "300 euros", "2 nuits", "train")
        for index, answer in enumerate(answers):
            question = session.open_questions[0]
            session = await engine.reply(
                session.id,
                FramingReply(
                    revision=session.revision,
                    question_id=question.id,
                    text=answer,
                ),
            )
            assert len(search.calls) == (1 if index == len(answers) - 1 else 0)

        assert session.status == FramingStatus.choosing_candidate
        assert len(search.calls) == 1
        assert session.slots[SlotName.date_window].value.startswith("April ")

    asyncio.run(run())


def test_country_hint_satisfies_location_question_but_month_does_not():
    class CountrySearch:
        def __init__(self):
            self.calls = []

        async def find_candidates(self, slots, request_text: str | None = None):
            self.calls.append(request_text)
            return [
                RaceCandidate(
                    id="china-half",
                    name="Beijing Half-Marathon",
                    city="Beijing",
                    country="CN",
                    race_date=date(2027, 10, 10),
                    distances_km=[21.0975],
                    sources=[Source(url="https://example.org/race")],
                    provenance=Provenance(
                        kind="fixture", url="https://example.org/race"
                    ),
                )
            ]

    async def run():
        finder = CountrySearch()
        session = await FramingEngine(finder, DataMode.demo).create(
            FramingCreate(text="Un semi marathon en Chine")
        )
        assert finder.calls == []
        assert session.open_questions[0].slots == [SlotName.date_window]
        assert SlotName.city not in {
            slot for question in session.open_questions for slot in question.slots
        }

        full_text = (
            "Un semi marathon en Chine en octobre 2027 depuis Paris, "
            "500 euros, 2 nuits, train"
        )
        complete = await FramingEngine(finder, DataMode.demo).create(
            FramingCreate(text=full_text)
        )
        assert finder.calls == [full_text]
        assert complete.open_questions[0].choices[0].candidate_id == "china-half"
        assert SlotName.city not in {
            slot for question in complete.open_questions for slot in question.slots
        }

        month_finder = Search()
        month = await FramingEngine(month_finder, DataMode.demo).create(
            FramingCreate(text="un semi en décembre")
        )
        assert month_finder.calls == []
        assert month.open_questions[0].slots == [SlotName.city]

    asyncio.run(run())


@pytest.mark.parametrize(
    "answer", ["PEU IMPORTE", "n'importe", "FLEXIBLE", "pas de préférence", "any time", "no preference"]
)
def test_flexible_date_window_is_marked_not_needed_and_flow_continues(answer):
    async def run():
        engine = FramingEngine(Search(1), DataMode.demo)
        session = await engine.create(
            FramingCreate(text="Un semi marathon à Pékin")
        )
        question = session.open_questions[0]
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                question_id=question.id,
                text=answer,
            ),
        )
        assert session.slots[SlotName.date_window].value is None
        assert session.slots[SlotName.date_window].status.value == "not_needed"
        assert session.open_questions[0].slots == [SlotName.origin]

    asyncio.run(run())


def test_candidate_search_retries_after_provider_error_on_later_reply():
    class FailOnceSearch:
        def __init__(self):
            self.calls = 0

        async def find_candidates(self, slots, request_text: str | None = None):
            self.calls += 1
            if self.calls == 1:
                raise CandidateSearchError("provider unavailable")
            return [
                RaceCandidate(
                    id="retry-candidate",
                    name="Tokyo City Run",
                    city=slots[SlotName.city].value,
                    country="JP",
                    race_date=date(2028, 6, 12),
                    distances_km=[10],
                    sources=[Source(url="https://example.org/race")],
                    provenance=Provenance(kind="fixture"),
                )
            ]

    async def run():
        search = FailOnceSearch()
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, avion"
                )
            )
        )
        assert search.calls == 1
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                corrections={SlotName.budget: 900},
            ),
        )
        assert search.calls == 2
        assert session.status == FramingStatus.choosing_candidate
        assert [candidate.id for candidate in session.candidates] == [
            "retry-candidate"
        ]

    asyncio.run(run())


def test_unrecognized_date_window_answer_is_kept_as_free_text():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(
            FramingCreate(text="Un semi marathon à Pékin")
        )
        question = session.open_questions[0]
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                question_id=question.id,
                text="au printemps",
            ),
        )
        assert session.slots[SlotName.date_window].value == "au printemps"

    asyncio.run(run())


def test_candidate_search_reuses_candidates_when_search_key_is_unchanged():
    async def run():
        search = Search(2)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, avion"
                )
            )
        )
        original_ids = [candidate.id for candidate in session.candidates]
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                question_id=session.open_questions[0].id,
                corrections={SlotName.budget: 500},
            ),
        )
        assert len(search.calls) == 1
        assert [candidate.id for candidate in session.candidates] == original_ids
        assert session.status == FramingStatus.choosing_candidate

    asyncio.run(run())


def test_french_date_correction_matches_canonical_english_search_key():
    async def run():
        search = Search(1)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(FramingCreate(
            text="Tokyo 10K in June 2028 from London, 800 euros, 2 nights, train",
        ))
        assert session.slots[SlotName.date_window].value == "June 2028"
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, corrections={SlotName.date_window: "juin 2028"},
        ))
        assert session.slots[SlotName.date_window].value == "June 2028"
        assert len(search.calls) == 1
        assert session.status == FramingStatus.choosing_candidate

    asyncio.run(run())


@pytest.mark.parametrize("language", ["English", "French"])
def test_bilingual_input_produces_english_questions_and_summary(language):
    async def run():
        from runai.framing.holo import TemplatePhraser

        engine = FramingEngine(Search(1), DataMode.demo, phraser=TemplatePhraser())
        text = (
            "Tokyo 10K in June 2028 from London, 800 euros, 2 nights, train"
            if language == "English" else
            "course de 10 km à Tokyo en juin 2028 depuis London, 800 euros, 2 nuits, train"
        )
        session = await engine.create(FramingCreate(text=text))
        assert session.status == FramingStatus.choosing_candidate
        assert session.turns[-1].text.startswith("I found a matching race.")
        assert session.open_questions[0].choices[-1].label == "None of these, let me clarify"
        assert session.slots[SlotName.distance_km].provenance.kind.value == "human"
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, choice_id="c0",
        ))
        assert session.status == FramingStatus.ready_to_confirm
        assert session.summary.lines[1] == "From London · 2 nights · train"
        assert session.summary.lines[2] == "Budget: €800"

    asyncio.run(run())


def test_changing_date_window_while_candidates_are_shown_searches_again():
    async def run():
        search = Search(1)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, avion"
                )
            )
        )
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                question_id=session.open_questions[0].id,
                corrections={SlotName.date_window: "juillet 2028"},
            ),
        )
        assert len(search.calls) == 2
        assert session.status == FramingStatus.choosing_candidate

    asyncio.run(run())


def test_conversational_period_change_replaces_derived_date_window():
    class DateWindowFiller:
        async def extract(self, text, known, turns=()):
            if text == "actually I'd rather go the following month":
                assert "date_window" not in known
                return {"date_window": "May 2028"}
            return {}

        async def phrase(self, turns, question, known):
            return question

    async def run():
        engine = FramingEngine(
            Search(1, distances=(42.195,)),
            DataMode.demo,
            phraser=DateWindowFiller(),
        )
        session = await engine.create(
            FramingCreate(
                text=(
                    "Marathon de Paris depuis Lyon en train, 2 nuits, 300 euros"
                )
            )
        )
        assert not session.slots[SlotName.date_window].is_known
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, choice_id="c0")
        )
        assert session.status == FramingStatus.ready_to_confirm
        session = await engine.reply(
            session.id, FramingReply(
                revision=session.revision, text="actually I'd rather go the following month"
            )
        )
        window = session.slots[SlotName.date_window]
        assert window.value == "May 2028"
        assert window.status.value == "answered"
        assert window.provenance.kind == "human"
        assert session.selected_candidate_id is None
        assert session.status == FramingStatus.choosing_candidate
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, choice_id="c0")
        )
        assert session.slots[SlotName.date_window] == window

    asyncio.run(run())


def test_changing_a_known_distance_invalidates_the_selected_candidate():
    async def run():
        search = Search(1, distances=(10,))
        engine = FramingEngine(search, DataMode.demo)
        session = await ready(engine)
        assert session.selected_candidate_id == "c0"
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                corrections={SlotName.distance_km: 21.0975},
            ),
        )
        assert session.selected_candidate_id is None
        assert len(search.calls) == 2
        assert session.status == FramingStatus.choosing_candidate

    asyncio.run(run())


def test_correcting_selected_candidate_edition_runs_search_again():
    async def run():
        search = Search(1)
        engine = FramingEngine(search, DataMode.demo)
        session = await ready(engine)
        assert session.slots[SlotName.edition].value == "2028"

        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                corrections={SlotName.edition: "2030"},
            ),
        )

        assert len(search.calls) == 2
        assert session.selected_candidate_id is None
        assert session.status == FramingStatus.choosing_candidate
        assert session.open_questions[0].choices[0].candidate_id == "c0"

    asyncio.run(run())


def test_changing_preferences_while_candidates_are_shown_runs_search_again():
    async def run():
        search = Search(1)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, avion"
                )
            )
        )

        session = await engine.reply(
            session.id,
            FramingReply(
                revision=session.revision,
                corrections={SlotName.preferences: "parcours ombragé"},
            ),
        )

        assert len(search.calls) == 2
        assert session.status == FramingStatus.choosing_candidate
        assert session.open_questions[0].choices[0].candidate_id == "c0"

    asyncio.run(run())


def test_named_race_request_skips_location_distance_and_period_questions():
    async def run():
        search = Search(1, distances=(42.195,))
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "Marathon de Paris depuis Lyon en train, "
                    "2 nuits, 300 euros"
                )
            )
        )
        assert session.slots[SlotName.race].value == "Marathon de Paris"
        assert len(search.calls) == 1
        assert session.open_questions[0].choices[0].candidate_id == "c0"
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, choice_id="c0")
        )
        assert session.status == FramingStatus.ready_to_confirm
        assert session.summary is not None

    asyncio.run(run())


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
        ("course à Tokyo en mars", "March 2027"),
        ("course à Tokyo en novembre", "November 2026"),
        ("course à Tokyo au mois de mai", "May 2027"),
    ],
)
def test_month_without_year_uses_next_occurrence(text, expected):
    assert normalize_date_window(extract_slots(text, today=date(2026, 11, 7))[SlotName.date_window]) == expected


def test_month_window_uses_explicit_edition_year():
    values = extract_slots(
        "course à Tokyo en mars édition 2030", today=date(2026, 11, 7)
    )
    assert normalize_date_window(values[SlotName.date_window]) == "March 2030"
    assert values[SlotName.edition] == "2030"


def test_candidates_selection_and_channel_parity():
    async def run():
        states = []
        for channel in ("text", "voice"):
            engine = FramingEngine(Search(2), DataMode.demo)
            session = await engine.create(
                FramingCreate(
                    text=(
                        "une course à Chicago, 10 km en juin 2028, depuis Lyon, "
                        "800 euros, 2 nuits, avion"
                    ),
                    channel=channel,
                )
            )
            assert session.status == FramingStatus.choosing_candidate
            assert session.slots[SlotName.race].value is None
            assert len(session.open_questions[0].choices) == 3
            assert session.open_questions[0].text == (
                "Which event would you like? Check the sources and edition."
            )
            session = await engine.reply(
                session.id, FramingReply(revision=1, choice_id="c1", channel=channel)
            )
            assert session.selected_candidate_id == "c1"
            assert session.status == FramingStatus.ready_to_confirm
            assert session.summary is not None
            assert session.slots[SlotName.distance_km].value == 10
            assert session.turns[-1].channel == channel
            states.append({k: s.value for k, s in session.slots.items()})
        assert states[0] == states[1]

    asyncio.run(run())


def test_close_candidates_use_close_match_choice_copy():
    async def run():
        session = await FramingEngine(
            Search(2, close_match=True), DataMode.demo
        ).create(
            FramingCreate(
                text=(
                    "course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, avion"
                )
            )
        )
        question = session.open_questions[0]
        assert question.text == (
            "I could not find your exact race. Here are the closest matches — "
            "which one interests you?"
        )
        assert question.choices[0].label == (
            "Race 0 — Monday 12 June 2028 · close to your request"
        )
        assert question.choices[-1].id == "none"
        assert question.choices[-1].label == "None of these, let me clarify"

    asyncio.run(run())


def test_close_match_distance_selection_uses_only_available_distance_or_asks():
    async def run():
        requested = (
            "une course à Tokyo, 21.1 km en juin 2028, depuis Lyon, "
            "800 euros, 2 nuits, en avion"
        )
        engine = FramingEngine(
            Search(1, close_match=True, distances=[10]), DataMode.demo
        )
        single = await engine.create(FramingCreate(text=requested))
        single = await engine.reply(
            single.id, FramingReply(revision=single.revision, choice_id="c0")
        )
        assert single.slots[SlotName.distance_km].value == 10
        assert single.status == FramingStatus.ready_to_confirm

        multiple_engine = FramingEngine(
            Search(1, close_match=True, distances=[10, 21]), DataMode.demo
        )
        multiple = await multiple_engine.create(
            FramingCreate(
                text=(
                    "une course à Tokyo, 42.195 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, en avion"
                )
            )
        )
        multiple = await multiple_engine.reply(
            multiple.id,
            FramingReply(
                revision=multiple.revision,
                question_id=multiple.open_questions[0].id,
                choice_id="c0",
            ),
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
            FramingCreate(
                text=(
                    "course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, train"
                )
            )
        )
        limitation = next(
            limitation
            for limitation in session.limitations
            if limitation.code == "no_candidates"
        )
        assert limitation.message == (
            "I found no matching race, even after broadening the search. "
            "Provide the official race name or its website URL."
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
        assert city_question.text == "Which city or country?"
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
                    SlotName.race: "Official race",
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
            raise RuntimeError("Unable to launch")

        with pytest.raises(RuntimeError):
            await engine.confirm(
                session.id, FramingConfirm(revision=3, idempotency_key="fail-key"), fail
            )
        assert engine.get(session.id).status == FramingStatus.ready_to_confirm
        with pytest.raises(RuntimeError, match="Service unavailable"):
            await FramingEngine(Search(fail=True)).create(
                FramingCreate(
                    text=(
                        "course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                        "800 euros, 2 nuits, train"
                    )
                )
            )

    asyncio.run(run())


def test_candidate_rejection_and_correction_preserve_known_answers():
    async def run():
        search = Search(2)
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(
            FramingCreate(
                text=(
                    "course à Nairobi, 10 km en juin 2028, depuis Mombasa, "
                    "900 euros, 2 nuits, bus"
                )
            )
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


def test_specific_period_correction_invalidates_selected_flexible_race():
    async def run():
        search = Search(1)
        engine = FramingEngine(search)
        session = await engine.create(FramingCreate(
            text="course à Tokyo, 10 km, depuis Lyon, 800 euros, 2 nuits, train"
        ))
        question = next(q for q in session.open_questions if q.slots == [SlotName.date_window])
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, question_id=question.id, text="any time"
        ))
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, choice_id="c0"
        ))
        assert session.status == FramingStatus.ready_to_confirm
        assert session.slots[SlotName.date_window].value is None
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, corrections={SlotName.date_window: "October"}
        ))
        assert session.selected_candidate_id is None
        assert session.summary is None
        assert session.status == FramingStatus.choosing_candidate
        assert len(search.calls) == 2
        assert search.calls[-1][SlotName.date_window].value == "October"

    asyncio.run(run())


@pytest.mark.parametrize("answer", ["no cap", "NO LIMIT", "Unlimited", "sans plafond", "Pas de limite"])
def test_budget_question_accepts_unlimited_answers(answer):
    async def run():
        engine = FramingEngine(Search(1))
        session = await engine.create(FramingCreate(
            text="course à Tokyo, 10 km en juin 2028, depuis Lyon, 2 nuits, train"
        ))
        question = next(q for q in session.open_questions if q.slots == [SlotName.budget])
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, question_id=question.id, text=answer
        ))
        assert session.slots[SlotName.budget].value is None
        assert session.slots[SlotName.budget].status.value == "not_needed"
        assert not any(SlotName.budget in q.slots for q in session.open_questions)
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, choice_id="c0"
        ))
        assert session.summary.lines[-1] == "Budget: no cap"

    asyncio.run(run())


def test_french_conjunction_car_is_not_a_transport_mode():
    assert SlotName.transport_mode not in extract_slots(
        "je viens car je veux courir à Tokyo"
    )
    assert extract_slots("j'y vais en voiture")[SlotName.transport_mode] == "car"


@pytest.mark.parametrize(
    "budget,nights,budget_line,stay",
    [(800.0, 2, "Budget: €800", "2 nights"),
     (800.5, 1, "Budget: €800.50", "1 night"),
     (1000000.0, 2, "Budget: €1000000", "2 nights"),
     (None, 0, "Budget: no cap", "0 nights")],
)
def test_summary_formats_human_values_without_changing_numbers(budget, nights, budget_line, stay):
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text="a race"))
        session = await engine.reply(
            session.id,
            FramingReply(revision=session.revision, corrections={
                SlotName.city: "Tokyo", SlotName.race: "City Marathon",
                SlotName.race_date: "2028-06-12", SlotName.distance_km: 42.195,
                SlotName.origin: "Lyon", SlotName.budget: budget,
                SlotName.nights: nights, SlotName.transport_mode: "train",
            }),
        )
        summary = session.summary
        assert summary.lines == [
            "City Marathon, Tokyo, Monday 12 June 2028, 42.2 km",
            f"From Lyon · {stay} · train", budget_line,
        ]
        assert summary.race.distance_km == 42.195
        assert summary.budget_eur == budget
        assert summary.nights == nights
        window = session.slots[SlotName.date_window]
        assert window.value == "2028-06-12"
        assert window.status == session.slots[SlotName.race_date].status
        assert window.provenance.kind == "derived"

    asyncio.run(run())


@pytest.mark.parametrize("explicit_window", [None, "June 2028"])
def test_sourced_date_derives_period_without_overriding_explicit_answer(explicit_window):
    async def run():
        engine = FramingEngine(Search(1), DataMode.demo)
        session = await engine.create(FramingCreate(text="a race"))
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, corrections={
                SlotName.city: "Tokyo", SlotName.distance_km: 10,
                SlotName.date_window: explicit_window, SlotName.origin: "Lyon",
                SlotName.budget: 800, SlotName.nights: 2, SlotName.transport_mode: "train",
            },
        ))
        before = session.slots[SlotName.date_window]
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, choice_id="c0",
        ))
        assert session.slots[SlotName.date_window] == before

    asyncio.run(run())


def test_sourced_date_fills_unknown_period():
    async def run():
        engine = FramingEngine(Search(1), DataMode.demo)
        session = await engine.create(FramingCreate(text="a race"))
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, corrections={
                SlotName.city: "Tokyo", SlotName.race: "City Run",
                SlotName.origin: "Lyon", SlotName.budget: 800,
                SlotName.nights: 2, SlotName.transport_mode: "train",
            },
        ))
        assert not session.slots[SlotName.date_window].is_known
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, choice_id="c0",
        ))
        window = session.slots[SlotName.date_window]
        assert window.value == "2028-06-12"
        assert window.status.value == "sourced"
        assert window.provenance.kind == "derived"

    asyncio.run(run())


def test_clearing_race_date_clears_derived_period():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text="race in Tokyo on 2028-06-12"))
        assert session.slots[SlotName.date_window].provenance.kind == "derived"
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, corrections={SlotName.race_date: None},
        ))
        window = session.slots[SlotName.date_window]
        assert not window.is_known
        assert window.value is None
        assert window.provenance is None
        assert any(q.slots == [SlotName.date_window] for q in session.open_questions)

    asyncio.run(run())


@pytest.mark.parametrize("city", ["Lyon", "Berlin"])
def test_bare_city_answer_preserves_chip_origin(city):
    async def run():
        engine = FramingEngine(Search())
        session = await engine.create(
            FramingCreate(text="Un marathon au printemps, depuis Lyon")
        )
        assert session.slots[SlotName.origin].value == "Lyon"
        session = await engine.reply(
            session.id, FramingReply(revision=session.revision, text=city)
        )
        assert session.slots[SlotName.city].value == city
        session = await engine.reply(
            session.id,
            FramingReply(revision=session.revision, corrections={SlotName.city: "Milan", SlotName.race: "Milano Marathon"}),
        )
        assert session.slots[SlotName.origin].value == "Lyon"
        assert session.slots[SlotName.origin].provenance.kind == "human"
        assert not any(SlotName.origin in q.slots for q in session.open_questions)

    asyncio.run(run())


def test_known_race_date_retires_discovery_slots_and_formats_summary():
    async def run():
        engine = FramingEngine(Search())
        session = await engine.create(FramingCreate(text="Un marathon au printemps, depuis Lyon"))
        session = await engine.reply(
            session.id,
            FramingReply(revision=session.revision, corrections={
                SlotName.city: "Milan", SlotName.race: "Milano Marathon",
                SlotName.race_date: "2027-04-11", SlotName.budget: 800,
                SlotName.nights: 2, SlotName.transport_mode: "train",
            }),
        )
        assert session.slots[SlotName.date_window].is_known
        assert not any(SlotName.date_window in q.slots for q in session.open_questions)
        assert session.summary.lines == [
            "Milano Marathon, Milan, Sunday 11 April 2027, 42.2 km",
            "From Lyon · 2 nights · train", "Budget: €800",
        ]
        session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={SlotName.budget: None}))
        assert session.summary.lines[-1] == "Budget: no cap"
        session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={SlotName.budget: 129.5}))
        assert session.summary.lines[-1] == "Budget: €129.50"

    asyncio.run(run())
