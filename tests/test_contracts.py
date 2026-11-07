import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from runai.contracts import load_fixture
from runai.contracts.common import DataMode
from runai.contracts.framing import (
    REQUIRED_SLOTS,
    FramingConfirm,
    FramingError,
    FramingReply,
    FramingSession,
    FramingStatus,
    SlotStatus,
    assert_launchable,
    check_reply_revision,
    missing_slots,
)
from runai.contracts.journey import (
    Budget,
    ChapterId,
    CostCategory,
    CostLine,
    JourneyPlan,
)
from runai.contracts.mission import EventEnvelope, HumanQuestion, MissionSnapshot
from runai.models import AgentQuestion, Race, StepKind, StepResult

ROOT = Path(__file__).resolve().parents[1]
JOURNEYS = ["journey_train.json", "journey_flight.json", "journey_incomplete.json"]
KEY = "confirm-0001"


@pytest.mark.parametrize("name", JOURNEYS)
def test_journey_fixtures_validate_and_cover_all_chapters(name):
    plan = JourneyPlan.model_validate(load_fixture(name))
    assert plan.mode is DataMode.demo
    assert [c.id for c in plan.chapters] == list(ChapterId)
    assert not any(stop.kind.value == "home" and "rue" in stop.label.lower() for stop in plan.stops)


def test_train_and_flight_fixtures_use_distinct_main_modes():
    modes = {
        name: {s.mode.value for s in JourneyPlan.model_validate(load_fixture(name)).segments}
        for name in JOURNEYS[:2]
    }
    assert "train" in modes["journey_train.json"] and "flight" not in modes["journey_train.json"]
    assert "flight" in modes["journey_flight.json"] and "train" not in modes["journey_flight.json"]


def test_incomplete_fixture_is_partial_with_explicit_limitations():
    plan = JourneyPlan.model_validate(load_fixture("journey_incomplete.json"))
    assert plan.timezone == "America/Chicago"
    assert any(stop.coords is None for stop in plan.stops)
    assert plan.budget.complete is False
    assert plan.budget.missing_line_ids == ["c-hotel", "c-flight"]
    assert plan.budget.over_cap is None
    assert all(seg.automation.value == "not_covered" for seg in plan.segments)
    assert plan.limitations[0].manual_url is not None


def test_budget_never_counts_missing_lines_as_zero():
    lines = [CostLine(id="a", category=CostCategory.registration, label="x")]
    assert Budget(cap=10, lines=lines).over_cap is None
    assert Budget(lines=[]).complete is False


def test_journey_rejects_dangling_references_and_fake_geometry():
    data = load_fixture("journey_train.json")
    data["segments"][0]["to_stop_id"] = "nowhere"
    with pytest.raises(ValidationError, match="nowhere"):
        JourneyPlan.model_validate(data)
    data = load_fixture("journey_train.json")
    race = next(s for s in data["segments"] if s["mode"] == "race")
    race["geometry"] = [[0, 0], [1, 1]]
    with pytest.raises(ValidationError, match="unavailable"):
        JourneyPlan.model_validate(data)


def test_vague_request_infers_nothing_but_the_city():
    session = FramingSession.model_validate(load_fixture("framing_vague.json"))
    assert session.status is FramingStatus.collecting
    known = {name for name, slot in session.slots.items() if slot.status is not SlotStatus.unknown}
    assert {k.value for k in known} == {"city"}
    assert set(missing_slots(session)) == set(REQUIRED_SLOTS)
    with pytest.raises(FramingError):
        assert_launchable(session, FramingConfirm(revision=session.revision, idempotency_key=KEY))


def test_candidates_are_sourced_and_offered_as_choices():
    session = FramingSession.model_validate(load_fixture("framing_candidates.json"))
    assert session.status is FramingStatus.choosing_candidate
    assert len(session.candidates) == 2 and all(c.sources for c in session.candidates)
    ids = {c.candidate_id for c in session.open_questions[0].choices}
    assert ids == {c.id for c in session.candidates}
    race = session.candidates[0].to_race()
    assert isinstance(race, Race) and race.distance_km is None


def test_confirmation_requires_current_revision_and_is_idempotent():
    session = FramingSession.model_validate(load_fixture("framing_ready.json"))
    assert not missing_slots(session)
    with pytest.raises(FramingError, match="révision 4"):
        assert_launchable(session, FramingConfirm(revision=4, idempotency_key=KEY))
    assert assert_launchable(session, FramingConfirm(revision=5, idempotency_key=KEY)) is None
    session.mission_id, session.confirm_key, session.status = "m1", KEY, FramingStatus.launched
    assert assert_launchable(session, FramingConfirm(revision=5, idempotency_key=KEY)) == "m1"
    with pytest.raises(FramingError, match="déjà lancée"):
        assert_launchable(session, FramingConfirm(revision=5, idempotency_key="other-key-1"))


def test_correction_after_summary_invalidates_launch():
    session = FramingSession.model_validate(load_fixture("framing_ready.json"))
    session.revision += 1
    with pytest.raises(FramingError, match="obsolète"):
        assert_launchable(session, FramingConfirm(revision=session.revision, idempotency_key=KEY))


def test_stale_or_cancelled_replies_are_rejected():
    session = FramingSession.model_validate(load_fixture("framing_candidates.json"))
    check_reply_revision(session, FramingReply(revision=2, text="la B"))
    with pytest.raises(FramingError, match="obsolète"):
        check_reply_revision(session, FramingReply(revision=1, text="la B"))
    session.status = FramingStatus.cancelled
    with pytest.raises(FramingError):
        check_reply_revision(session, FramingReply(revision=2, text="la B"))
    with pytest.raises(FramingError):
        assert_launchable(session, FramingConfirm(revision=2, idempotency_key=KEY))


def test_mission_snapshot_and_events_fixtures():
    snapshot = MissionSnapshot.model_validate(load_fixture("mission_snapshot.json"))
    assert all(isinstance(step, StepResult) for step in snapshot.steps)
    assert snapshot.questions[0].mission_id == snapshot.mission_id
    events = [EventEnvelope.model_validate(e) for e in load_fixture("events.json")]
    assert [e.sequence for e in events] == list(range(len(events)))
    assert events[0].to_sse().startswith("id: fx-mission:0\nevent: snapshot\n")


def test_human_question_wraps_v1_agent_question():
    question = AgentQuestion(id="q1", kind=StepKind.accommodation, question="Budget ?", options=["100 €"])
    wrapped = HumanQuestion.from_agent_question(question, mission_id="m1", revision=3, session_id="s1")
    assert (wrapped.question_id, wrapped.step, wrapped.status.value) == ("q1", StepKind.accommodation, "open")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_js_journey_contract_accepts_python_fixtures():
    result = subprocess.run(
        ["node", "--test", str(ROOT / "web" / "flyover" / "tests" / "journey-contract.test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
