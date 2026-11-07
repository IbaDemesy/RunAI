import asyncio
import json
import time
from datetime import date
from functools import partial

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app
from runai.app.store import MissionStore
from runai.app.tasks import TripBrief
from runai.contracts.framing import FramingSummary, FramingTurn
from runai.framing.launch import LaunchPlan, StepPlan
from runai.models import AgentQuestion, Race, StepKind

AGENT_STEPS = (StepKind.registration, StepKind.accommodation, StepKind.transport)


def start_mission(client, service):
    race = Race(name="Tokyo 10K", city="Tokyo", country="JP", race_date=date(2028, 6, 12), distance_km=10)
    summary = FramingSummary(revision=1, race=race, origin_public="Lyon", nights=2,
                             date_range=(date(2028, 6, 11), date(2028, 6, 13)),
                             budget_eur=1000, transport_mode="flight", lines=[])
    plan = LaunchPlan(framing_id="store-framing", revision=1, mode="demo", race=race,
                      brief=TripBrief(race_label=race.name, city=race.city, country=race.country),
                      steps={kind: StepPlan(kind=kind, automation="automated", task="Stop before payment")
                             for kind in AGENT_STEPS})
    return client.portal.call(partial(service.create, plan, summary=summary,
                                      turns=[FramingTurn(role="user", text="Plan my Tokyo race", revision=1)]))


def finish_mission(client, mission_id):
    route = f"/api/missions/{mission_id}"
    for _ in range(200):
        snapshot = client.get(route).json()
        if snapshot["status"] in {"awaiting_human", "completed", "failed", "cancelled"}:
            return snapshot
        for question in snapshot["questions"]:
            if question["status"] == "open":
                response = client.post(f"{route}/questions/{question['question_id']}/answer", json={
                    "answer": question["choices"][0], "revision": question["revision"],
                    "idempotency_key": f"store-{question['question_id']}",
                })
                assert response.status_code == 200
        time.sleep(.005)
    pytest.fail("Demo mission did not finish")


def test_completed_demo_survives_restart_with_journey_exports_and_event_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    original = build_demo_service(delay=0)
    with TestClient(create_app(original)) as client:
        mission = start_mission(client, original)
        before = finish_mission(client, mission.id)
        assert before["status"] == "awaiting_human"
        route = f"/api/missions/{mission.id}"
        journey = client.get(f"{route}/journey").json()
        recap = client.get(f"{route}/recap.html").text
        events = client.get(f"{route}/events").text

    restored = build_demo_service(delay=0)
    with TestClient(create_app(restored)) as client:
        response = client.get(route)
        assert response.status_code == 200
        assert response.json() == before
        assert response.json()["race"]["name"] == "Tokyo 10K"
        assert client.get(f"{route}/journey").json() == journey
        html = client.get(f"{route}/recap.html")
        assert html.status_code == 200 and html.text == recap
        assert client.get(f"{route}/recap.pdf").content.startswith(b"%PDF")
        assert client.get(f"{route}/recap.ics").status_code == 200
        assert client.get(f"{route}/events").text == events
        envelopes = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
        cursor = envelopes[2]["event_id"]
        replay = client.get(f"{route}/events", headers={"Last-Event-ID": cursor})
        assert [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")] == envelopes[3:]
        assert client.get(f"{route}/events", headers={"Last-Event-ID": envelopes[-1]["event_id"]}).text == ""
        assert client.get(f"{route}/events", headers={"Last-Event-ID": "other:1"}).status_code == 409
        assert not restored._mission_tasks
        for action in ("cancel", "pause", "resume"):
            assert client.post(f"{route}/{action}").status_code == 409
        question = before["questions"][0]
        assert client.post(f"{route}/questions/{question['question_id']}/answer", json={
            "answer": "No", "revision": question["revision"], "idempotency_key": "read-only-test",
        }).status_code == 409


def test_interrupted_mission_fails_on_restart_without_resuming_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    original = build_demo_service(delay=0)
    with TestClient(create_app(original)) as client:
        mission = start_mission(client, original)
        route = f"/api/missions/{mission.id}"
        restarted = build_demo_service(delay=0)
        with TestClient(create_app(restarted)) as recovered:
            snapshot = recovered.get(route)
            assert snapshot.status_code == 200
            snapshot = snapshot.json()
            assert snapshot["status"] == "failed"
            assert any(item["code"] == "server_restarted" for item in snapshot["limitations"])
            assert all(step["status"] not in {"running", "paused", "pending", "waiting_for_user"}
                       for step in snapshot["steps"])
            assert recovered.get(f"{route}/journey").status_code == 200
            assert recovered.get(f"{route}/recap.html").status_code == 200
            events = recovered.get(f"{route}/events").text
            assert '"status":"failed"' in events
            assert not restarted._mission_tasks and not restarted._runs
        with TestClient(create_app(build_demo_service(delay=0))) as recovered_again:
            assert recovered_again.get(route).json() == snapshot
            assert recovered_again.get(f"{route}/events").text == events


@pytest.mark.anyio
async def test_active_saves_are_coalesced_and_terminal_saves_flush_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    race = Race(name="Debounce race", city="Tokyo", country="JP")
    plan = LaunchPlan(framing_id="debounce", revision=1, mode="demo", race=race,
                      brief=TripBrief(race_label=race.name, city=race.city, country=race.country),
                      steps={kind: StepPlan(kind=kind, automation="automated", task="Stop before payment")
                             for kind in AGENT_STEPS})
    mission = await service.create(plan)
    path = tmp_path / "missions" / f"{mission.id}.json"
    assert path.exists()
    initial = path.read_bytes()
    for index in range(10):
        mission.error = f"Progress {index}"
        service._publish_state(mission)
    assert path.read_bytes() == initial
    await asyncio.sleep(.55)
    assert json.loads(path.read_text())["snapshot"]["error"] == "Progress 9"
    assert not mission.is_terminal
    await service.cancel(mission.id)
    assert json.loads(path.read_text())["snapshot"]["status"] == "cancelled"


@pytest.mark.parametrize("mission_id", ["../escape", "/absolute", "", ".", "two/parts", "unsafe.name"])
def test_store_rejects_unsafe_mission_ids(tmp_path, mission_id):
    with pytest.raises(ValueError, match="Invalid mission ID"):
        MissionStore(tmp_path).save(mission_id, lambda: None)
    assert not (tmp_path / "missions").exists()


def test_store_io_failure_preserves_previous_document_and_does_not_strand_mission(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mission = start_mission(client, service)
        path = tmp_path / "missions" / f"{mission.id}.json"
        previous = path.read_bytes()

        def unavailable(*args):
            raise OSError("Disk unavailable")

        monkeypatch.setattr("runai.app.store.os.replace", unavailable)
        assert finish_mission(client, mission.id)["status"] == "awaiting_human"
        assert path.read_bytes() == previous
        assert list(path.parent.glob("*.tmp")) == []


def test_store_skips_corrupt_and_cross_mission_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mission = start_mission(client, service)
        finish_mission(client, mission.id)
    directory = tmp_path / "missions"
    document = json.loads((directory / f"{mission.id}.json").read_text())
    (directory / "broken.json").write_text("{unfinished", encoding="utf-8")
    (directory / "wrong-id.json").write_text(json.dumps(document), encoding="utf-8")
    invalid = json.loads(json.dumps(document))
    invalid["envelopes"][0]["mission_id"] = "other"
    (directory / f"{mission.id}.json").write_text(json.dumps(invalid), encoding="utf-8")
    assert MissionStore(tmp_path).load() == []
    (directory / f"{mission.id}.json").write_text(json.dumps(document), encoding="utf-8")
    assert [item.snapshot.mission_id for item in MissionStore(tmp_path).load()] == [mission.id]


def test_store_redacts_all_fields_on_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    secret = "FAKE-MISSION-STORE-SECRET"
    monkeypatch.setenv("HAI_API_KEY_2", secret)
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mission = start_mission(client, service)
        finish_mission(client, mission.id)
        mission.error = secret
        mission.plan.brief.preferences = secret
        mission.framing_summary.lines = [secret]
        mission.framing_turns[0].text = secret
        client.portal.call(service._publish_state, mission)
        path = tmp_path / "missions" / f"{mission.id}.json"
        content = path.read_text()
        assert secret not in content and "[REDACTED]" in content
        assert not list(path.parent.glob("*.tmp"))
        assert path.stat().st_mode & 0o777 == 0o600
    document = json.loads(content)
    document["plan"]["brief"]["preferences"] = secret
    path.write_text(json.dumps(document), encoding="utf-8")
    restored = MissionStore(tmp_path).load()[0]
    assert secret not in restored.model_dump_json()
    assert restored.plan.brief.preferences == "[REDACTED]"


def test_eligibility_answer_after_completion_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mission = start_mission(client, service)
        finish_mission(client, mission.id)
        question = AgentQuestion(id=f"eligibility-{mission.id}-group", kind=StepKind.registration,
                                 question="Which start group should you review?", options=["Standard", "Fast"])

        def open_question():
            wrapped = service.questions.open(question, mission.id, mission.plan.revision)
            service._emit(mission, "question_opened", wrapped.model_dump(mode="json"))
            service._publish_state(mission)

        client.portal.call(open_question)
        route = f"/api/missions/{mission.id}"
        response = client.post(f"{route}/questions/{question.id}/answer", json={
            "answer": "Standard", "revision": 1, "idempotency_key": "persist-eligibility-answer",
        })
        assert response.status_code == 200
        answered = next(item for item in response.json()["questions"] if item["question_id"] == question.id)
        assert answered["status"] == "answered"
        events = client.get(f"{route}/events").text

    with TestClient(create_app(build_demo_service(delay=0))) as client:
        restored = next(item for item in client.get(route).json()["questions"] if item["question_id"] == question.id)
        assert restored["status"] == "answered" and restored["answer"] == "Standard"
        assert client.get(f"{route}/events").text == events
