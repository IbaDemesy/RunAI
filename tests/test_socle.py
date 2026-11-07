from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StopPoint,
    TraceEvent,
)
from runai.safety import STOP_INSTRUCTIONS, detect_stop_point, guard_task
from runai.tracing import TraceWriter


def test_default_profile_is_fake():
    assert RunnerProfile().email.endswith("@example.com")


def test_race_accepts_partial_data():
    race = Race(name="Milano Marathon", city="Milan", country="IT")
    assert race.sources == []


def test_guard_task_appends_stop_rules():
    assert guard_task("Ouvre la page d'inscription").endswith(STOP_INSTRUCTIONS)


def test_detect_stop_point():
    assert detect_stop_point("Proceed to payment") is StopPoint.payment
    assert detect_stop_point("Créer un compte pour continuer") is StopPoint.account_creation
    assert detect_stop_point("Joindre votre certificat médical") is StopPoint.health_declaration
    assert detect_stop_point("J'accepte le règlement") is StopPoint.consent
    assert detect_stop_point("Choisissez votre distance") is None


def test_trace_roundtrip(tmp_path):
    writer = TraceWriter("mission-1", traces_dir=tmp_path)
    writer.write(TraceEvent(source="h", type="step", message="page ouverte"))
    assert writer.read()[0].message == "page ouverte"


def test_step_result_defaults():
    assert StepResult(kind=StepKind.registration).status.value == "pending"
