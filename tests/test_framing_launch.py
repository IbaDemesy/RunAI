from datetime import date

import pytest

from runai.app.tasks import build_task
from runai.contracts import load_fixture
from runai.contracts.common import Automation
from runai.contracts.framing import (
    FramingError,
    FramingSession,
    FramingStatus,
    SlotName,
)
from runai.framing.launch import plan_launch
from runai.models import Race, RunnerProfile, StepKind
from runai.safety import STOP_INSTRUCTIONS

HARDCODED_V1 = (
    "Milan",
    "Paris",
    "2027",
    "42,195",
    "42.195",
    "Accor",
    "renitalia",
    "Corso",
)


def confirmed(**changes) -> FramingSession:
    session = FramingSession.model_validate(load_fixture("framing_ready.json"))
    for key, value in changes.items():
        if key == "slots":
            for name, slot_value in value.items():
                session.slots[name].value = slot_value
        elif key == "summary":
            session.summary = session.summary.model_copy(update=value)
        elif key == "candidate":
            candidate = session.candidates[1]
            for attr, attr_value in value.items():
                setattr(candidate, attr, attr_value)
        else:
            setattr(session, key, value)
    session.status = FramingStatus.confirmed
    session.confirmed_revision = session.revision
    return session


def milan_train() -> FramingSession:
    race = {
        "name": "Course fictive de Milan",
        "city": "Milan",
        "country": "IT",
        "race_date": date(2027, 10, 3),
        "distance_km": 10.0,
        "sources": [],
    }
    return confirmed(
        summary={
            "race": Race(**race),
            "origin_public": "Turin",
            "transport_mode": "train",
            "date_range": (date(2027, 10, 2), date(2027, 10, 4)),
            "nights": 2,
            "budget_eur": 600.0,
            "limitations": [],
        },
        slots={SlotName.distance_km: 10.0, SlotName.race_date: "2027-10-03"},
        candidate={"registration_url": "https://in.njuko.com/fictive-milan"},
    )


def lisbon_klikego() -> FramingSession:
    race = {
        "name": "Corrida fictive de Lisbonne",
        "city": "Lisbonne",
        "country": "PT",
        "race_date": date(2028, 3, 12),
        "distance_km": 21.0975,
        "sources": [],
    }
    return confirmed(
        summary={
            "race": Race(**race),
            "origin_public": "Bordeaux",
            "transport_mode": "train",
            "date_range": (date(2028, 3, 11), date(2028, 3, 14)),
            "nights": 3,
            "budget_eur": 900.0,
            "limitations": [],
        },
        slots={SlotName.race_date: "2028-03-12", SlotName.preferences: "chambre calme"},
        candidate={"registration_url": "https://www.klikego.com/fictive-lisbonne"},
    )


def test_tokyo_out_of_europe_plan_comes_from_confirmed_summary():
    plan = plan_launch(confirmed())

    assert plan.race.city == "Tokyo" and plan.race.distance_km == 21.0975
    assert plan.race.race_date == date(2028 - 1, 4, 18)
    assert plan.brief.origin == "Lyon" and plan.brief.nights == 4
    assert plan.brief.budget_total_eur == 1800
    registration = plan.steps[StepKind.registration]
    assert registration.automation is Automation.not_covered
    assert registration.limitations[0].code == "registration_link_missing"
    assert str(registration.limitations[0].manual_url) == "https://example.org/tokyo-b"
    transport = plan.steps[StepKind.transport]
    assert transport.automation is Automation.manual and transport.task is None
    assert "TAP forbidden" in transport.limitations[0].message
    accommodation = plan.steps[StepKind.accommodation]
    assert accommodation.automation is Automation.automated
    task = accommodation.task
    assert "Tokyo (JP)" in task and "Friday 16 April 2027" in task and "Tuesday 20 April 2027" in task
    assert "(4 nights)" in task and "PRIX_TOTAL_4_NUITS" in task
    assert "1800 EUR for everything" in task
    assert task.endswith(STOP_INSTRUCTIONS)
    assert not any(word in task for word in ("Milan", "Paris", "Corso", "42,195", "42.195"))
    assert plan.automated_steps() == [StepKind.accommodation]


def test_milan_train_with_njuko_automates_three_steps_without_v1_strings():
    plan = plan_launch(milan_train())

    assert plan.automated_steps() == list(StepKind)[1:]
    assert plan.brief.budget_open is False
    assert (
        plan.steps[StepKind.registration].start_url
        == "https://in.njuko.com/fictive-milan"
    )
    registration = plan.steps[StepKind.registration].task
    transport = plan.steps[StepKind.transport].task
    assert (
        "Course fictive de Milan 2027 on Njuko" in registration
        and "(10 km)" in registration
    )
    assert "Runcard" not in registration and "Klikego" in registration
    assert "camille.test@example.com" in registration
    assert "Turin → Milan" in transport and "trenitalia.com" in transport
    assert "Saturday 2 October 2027" in transport and "never TAP" in transport
    assert "Paris" not in transport


def test_confirmed_no_budget_is_preserved_as_open_budget():
    plan = plan_launch(confirmed(summary={"budget_eur": None}))

    assert plan.brief.budget_total_eur is None
    assert plan.brief.budget_open is True


def test_lisbon_klikego_link_is_manual_and_train_has_no_validated_vendor():
    plan = plan_launch(lisbon_klikego())

    registration = plan.steps[StepKind.registration]
    assert registration.automation is Automation.manual and registration.task is None
    assert "Klikego is forbidden" in registration.limitations[0].message
    assert "klikego.com" in str(registration.limitations[0].manual_url)
    transport = plan.steps[StepKind.transport]
    assert transport.automation is Automation.manual
    assert "PT" in transport.limitations[0].message
    task = plan.steps[StepKind.accommodation].task
    assert (
        "Lisbonne (PT)" in task
        and "chambre calme" in task
        and "PRIX_TOTAL_3_NUITS" in task
    )
    codes = {(limit.code, limit.step) for limit in plan.limitations}
    assert ("registration_platform_forbidden", "registration") in codes


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: setattr(s, "status", FramingStatus.ready_to_confirm),
        lambda s: setattr(s, "confirmed_revision", s.revision - 1),
        lambda s: setattr(s, "status", FramingStatus.cancelled),
        lambda s: setattr(s, "summary", s.summary.model_copy(update={"revision": 4})),
        lambda s: setattr(s.slots[SlotName.origin], "status", "unknown"),
        lambda s: setattr(s, "selected_candidate_id", "absent"),
        lambda s: setattr(s, "summary", s.summary.model_copy(update={"nights": 3})),
    ],
)
def test_launch_refuses_unconfirmed_stale_or_inconsistent_framing(mutate):
    session = confirmed()
    mutate(session)
    with pytest.raises(FramingError):
        plan_launch(session)


def test_unknown_values_become_questions_not_inventions():
    from runai.app.tasks import TripBrief

    race = confirmed().summary.race
    brief = TripBrief(
        race_label="Course X",
        city="Nairobi",
        country="KE",
        accommodation_site="site officiel Accor",
        transport_site="vendeur test",
    )
    accommodation = build_task(
        StepKind.accommodation, race, RunnerProfile(), brief=brief
    )
    transport = build_task(StepKind.transport, race, RunnerProfile(), brief=brief)
    registration = build_task(
        StepKind.registration,
        race.model_copy(update={"distance_km": None}),
        RunnerProfile(),
        brief=brief,
    )
    assert (
        "stay dates unknown" in accommodation
        and "PRIX_TOTAL_SEJOUR" in accommodation
    )
    assert "Max budget per night" in accommodation
    assert "origin city unknown" in transport and "dates unknown" in transport
    assert "distance unknown" in registration
    with pytest.raises(ValueError, match="not automated"):
        build_task(
            StepKind.transport,
            race,
            RunnerProfile(),
            brief=brief.model_copy(update={"transport_site": None}),
        )


def test_tasks_module_has_no_v1_hardcoded_values():
    from pathlib import Path

    from runai.app import tasks

    source = Path(tasks.__file__).read_text(encoding="utf-8")
    assert not [word for word in HARDCODED_V1 if word in source]


def test_zero_nights_skips_accommodation_instead_of_failing():
    session = confirmed()
    day = session.summary.race.race_date
    session.summary = session.summary.model_copy(
        update={"nights": 0, "date_range": (day, day)}
    )
    session.slots[SlotName.nights].value = 0
    plan = plan_launch(session)
    assert plan.steps[StepKind.accommodation].automation is Automation.not_covered
    assert plan.steps[StepKind.accommodation].task is None
    assert any(lim.code == "no_accommodation_requested" for lim in plan.limitations)


def test_confirmed_plan_starts_accommodation_on_accor_results_page():
    plan = plan_launch(milan_train())

    accommodation = plan.steps[StepKind.accommodation]
    assert accommodation.start_url == (
        "https://all.accor.com/booking/en/accor/hotels/milan-italy"
        "?dateIn=2027-10-02&nights=2&compositions=1"
    )
    assert accommodation.start_url_kind == "deep_link"
    assert plan.brief.accommodation_url == accommodation.start_url
    transport = plan.steps[StepKind.transport]
    assert transport.start_url == "https://www.trenitalia.com/en.html"
    assert transport.start_url_kind == "home"
