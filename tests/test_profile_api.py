from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import DEMO_RACES
from runai.app.profile import ProfileStore
from runai.app.server import build_demo_service, create_app
from runai.app.tasks import TripBrief, build_task
from runai.models import RunnerProfile, StepKind, utcnow


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    return build_demo_service(delay=0)


def test_default_profile(service):
    with TestClient(create_app(service)) as client:
        response = client.get("/api/profile")
        assert response.status_code == 200
        assert response.json() == RunnerProfile().model_dump(mode="json")


@pytest.mark.parametrize("body", [
    {"email": "runner@real.org"},
    {"email": "invalid"},
    {"phone": []},
    {"unknown": "value"},
    {"email": "runner@real.org", "confirm_real_data": "true"},
])
def test_invalid_profile(service, body, tmp_path):
    with TestClient(create_app(service)) as client:
        assert client.put("/api/profile", json=body).status_code == 422
    assert not (tmp_path / "profile.json").exists()
    assert service.profile.fictional


def test_save_reload_and_render_profile(service):
    with TestClient(create_app(service)) as client:
        response = client.put("/api/profile", json={
            "email": "runner@real.org", "confirm_real_data": True,
            "phone": "+33123456789", "license_number": "private-license-123456789",
            "birth_date": "1990-02-03",
        })
        assert response.status_code == 200
        assert response.json()["fictional"] is False
        assert response.json()["license_number"] == "[REDACTED]"
        assert client.get("/api/profile").json()["license_number"] == "[REDACTED]"
    loaded = build_demo_service(delay=0)
    assert loaded.profile == service.profile
    assert loaded.profile.fictional is False
    task = build_task(StepKind.registration, DEMO_RACES["milan"], loaded.profile,
                      brief=TripBrief(race_label="Race", city="Milan", country="IT"))
    assert "phone: +33123456789" in task
    assert "Runner profile:" in task
    assert "emergency contact" not in task


@pytest.mark.parametrize("content", [None, "not json", '{"birth_date":"bad"}', "[]"])
def test_invalid_or_absent_store(tmp_path, content):
    path = tmp_path / "profile.json"
    if content is not None:
        path.write_text(content)
    assert ProfileStore(path).load() == RunnerProfile()


def test_prefill_latest_and_user_filter(service):
    now = utcnow()
    for index, user_id in enumerate(["alice", "bob", None]):
        brief = TripBrief(race_label="Race", city="Paris", country="FR",
                          origin=f"City {index}", transport_mode="train",
                          budget_total_eur=300 + index, nights=2, preferences="Quiet")
        mission = SimpleNamespace(created_at=now + timedelta(seconds=index),
                                  plan=SimpleNamespace(brief=brief))
        if user_id is not None:
            mission.user_id = user_id
        service.missions[str(index)] = mission
    service.missions["unconfirmed"] = SimpleNamespace(plan=None)
    client = TestClient(create_app(service))
    assert client.get("/api/prefill").json() == {
        "origin": "City 2", "transport_mode": "train", "budget_total_eur": 302,
        "nights": 2, "preferences": "Quiet",
    }
    assert client.get("/api/prefill?user_id=alice").json()["origin"] == "City 0"
    assert client.get("/api/prefill?user_id=missing").status_code == 404
    service.missions.clear()
    assert client.get("/api/prefill").status_code == 404
