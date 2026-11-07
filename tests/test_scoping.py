from datetime import date

import pytest
from fastapi.testclient import TestClient

from runai.app.scoping import ChatMessage, FakeScoper, Scope, parse_turn
from runai.app.server import build_demo_service, create_app
from runai.app.tasks import build_task
from runai.models import Race, RunnerProfile, StepKind


def _messages(*pairs):
    return [ChatMessage(role=role, content=content) for role, content in pairs]


@pytest.mark.anyio
async def test_fake_scoper_asks_only_what_is_missing():
    scoper = FakeScoper(delay=0)
    turn = await scoper.next_turn(
        _messages(("user", "Marathon de Milan, je pars de Lyon"))
    )
    assert not turn.ready
    assert "budget" in turn.reply.lower()
    assert turn.scope.departure_city == "Lyon"
    history = _messages(
        ("user", "Marathon de Milan, je pars de Lyon"),
        ("assistant", turn.reply),
        ("user", "120 €"),
    )
    turn = await scoper.next_turn(history)
    assert "justificatif" in turn.reply.lower()
    history += _messages(("assistant", turn.reply), ("user", "Licence FFA"))
    turn = await scoper.next_turn(history)
    assert turn.ready
    assert turn.scope.budget_per_night == 120
    assert turn.scope.medical == "Licence FFA"


@pytest.mark.anyio
async def test_fake_scoper_launches_on_go():
    turn = await FakeScoper(delay=0).next_turn(
        _messages(
            ("user", "Semi de Paris"),
            ("assistant", "D'où partez-vous ?"),
            ("user", "go"),
        )
    )
    assert turn.ready and turn.scope.race == "Semi de Paris"


def test_parse_turn_reads_json_and_tolerates_text():
    turn = parse_turn(
        '```json\n{"reply": "OK", "ready": true, "scope": {"race": "10 km de Lyon", "budget_per_night": 90}}\n```'
    )
    assert turn.ready and turn.scope.budget_per_night == 90
    plain = parse_turn("Quelle distance ?")
    assert plain.reply == "Quelle distance ?" and not plain.ready
    assert not parse_turn('{"reply": "Hm", "ready": true, "scope": {}}').ready


def test_scope_drives_generic_tasks():
    race = Race(
        name="JAL Honolulu Marathon",
        city="Honolulu",
        country="US",
        race_date=date(2026, 12, 13),
        distance_km=42.195,
        registration_url="https://www.letsdothis.com/honolulu",
    )
    scope = Scope(
        race="Honolulu",
        departure_city="Lyon",
        budget_per_night=150,
        travel_time="matin",
        medical="certificat",
    )
    query = scope.query()
    assert "certificat" in query and "certificat" not in scope.search_query()
    registration = build_task(
        StepKind.registration, race, RunnerProfile(), query=query, scope=scope
    )
    accommodation = build_task(
        StepKind.accommodation, race, RunnerProfile(), query=query, scope=scope
    )
    transport = build_task(
        StepKind.transport, race, RunnerProfile(), query=query, scope=scope
    )
    assert "letsdothis.com" in registration and "Njuko" not in registration
    assert "ne le redemande pas" in registration
    assert (
        "Honolulu" in accommodation
        and "12 décembre 2026" in accommodation
        and "14 décembre 2026" in accommodation
    )
    assert "300 € maximum" in accommodation
    assert (
        "Lyon → Honolulu" in transport and "avion" in transport and "matin" in transport
    )


@pytest.fixture
def client():
    with TestClient(create_app(build_demo_service(delay=0))) as test_client:
        yield test_client


def test_scope_endpoint_then_launch(client):
    turn = client.post(
        "/api/scope",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Marathon de Milan, je pars de Paris, hôtel 150 € par nuit",
                }
            ]
        },
    )
    assert turn.status_code == 200
    body = turn.json()
    assert body["scope"]["departure_city"] == "Paris"
    created = client.post(
        "/api/missions", json={"query": "Marathon de Milan", "scope": body["scope"]}
    )
    assert created.status_code == 201
    mission = created.json()
    assert mission["scope"]["budget_per_night"] == 150
    assert "Budget hôtel max 150 € par nuit" in mission["query"]
    assert client.post("/api/scope", json={"messages": []}).status_code == 422
