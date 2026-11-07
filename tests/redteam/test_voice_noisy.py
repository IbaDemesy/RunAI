import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from runai.app.mission import MissionService
from runai.app.server import MAX_AUDIO_BYTES, build_demo_service, create_app
from runai.voice.commands import extract_race, parse_command
from runai.voice.vocabulary import gladia_vocabulary


@pytest.mark.parametrize(("text", "kind", "target"), [
    ("attends non en fait continue", "resume", None),
    ("pause the registration but keep the hotel", "pause", "registration"),
    ("uh um pause the hotel", "pause", "accommodation"),
    ("euh euh attends attends", "pause", None),
    ("hum reprends le train", "resume", "transport"),
    ("uh resume registration", "resume", "registration"),
    ("um cancel the hotel", "cancel", "accommodation"),
    ("like like continue", "resume", None),
    ("pause actually resume", "resume", None),
    ("continue non attends", "pause", None),
    ("annule non en fait reprends", "resume", None),
    ("reprends finalement annule", "cancel", None),
    ("uh change the hotel", "correction", "accommodation"),
    ("euh muda o voo", "correction", "transport"),
    ("hum pausa o alojamento", "pause", "accommodation"),
    ("continua a inscricao", "resume", "registration"),
    ("cancela a inscricao", "cancel", "registration"),
    ("non n annule pas", None, None),
    ("do not cancel", None, None),
    ("ne pas annuler", None, None),
    ("nao cancela o hotel", None, None),
    ("non n annule pas le semi de Paris", None, None),
    ("", None, None),
    ("euh hum uh um", None, None),
    ("c-continue", "resume", None),
    ("I'd like to run the Tokyo ten k", "new_mission", None),
])
def test_noisy_commands(text, kind, target):
    command = parse_command(text)
    if kind is None:
        assert command is None
    else:
        assert command.kind.value == kind
        assert (command.target.value if command.target else None) == target


@pytest.mark.parametrize(("text", "city", "distance", "origin"), [
    ("I want to run the Tokyo ten k from London", "Tokyo", 10, "London"),
    ("uh Tokyo 10k from London", "Tokyo", 10, "London"),
    ("Tokyo 10 k depuis Londres", "Tokyo", 10, "London"),
    ("euh le dix km a Paris depuis Londres", "Paris", 10, "London"),
    ("quero correr dez km em Lisboa de Porto", "Lisbon", 10, "Porto"),
    ("half in Lisbon from London", "Lisbon", 21.0975, "London"),
    ("semi a Lisbonne depuis Paris", "Lisbon", 21.0975, "Paris"),
    ("meia maratona de Lisboa desde Porto", "Lisbon", 21.0975, "Porto"),
    ("marathon in London from Lisbon", "London", 42.195, "Lisbon"),
    ("from London Tokyo ten k", "Tokyo", 10, "London"),
    ("from London", None, None, "London"),
    ("marathon from London", None, 42.195, "London"),
    ("semi depuis Londres", None, 21.0975, "London"),
    ("meia meia maratona de Lisboa", "Lisbon", 21.0975, None),
    ("five kilometers in Barcelona", "Barcelona", 5, None),
    ("cinco quilometros em Lisboa", "Lisbon", 5, None),
    ("vingt kilometres a Paris", "Paris", 20, None),
    ("Tokyo Tokyo ten k", "Tokyo", 10, None),
    ("hum hello", None, None, None),
    ("", None, None, None),
])
def test_noisy_races(text, city, distance, origin):
    race = extract_race(text)
    if city is distance is origin is None:
        assert race is None
    else:
        assert (race.city, race.distance_km, race.origin) == (city, distance, origin)


def test_vocabulary_entry_count_is_unchanged():
    assert len(gladia_vocabulary()) == 32


@pytest.fixture
def demo_app(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    return create_app(service)


def test_transcribe_empty_and_random_bytes(demo_app):
    with TestClient(demo_app) as client:
        response = client.post("/api/transcribe", content=b"")
        assert response.status_code == 400
        assert "Traceback" not in response.text
        response = client.post("/api/transcribe", content=b"\xff\x00\x81random")
        assert response.status_code == 200
        assert response.json()["mode"] == "demo"


def test_transcribe_rejects_large_header_before_reading(demo_app, monkeypatch):
    async def unread_stream(self):
        raise AssertionError("Body must not be read")
        yield b""

    monkeypatch.setattr(Request, "stream", unread_stream)
    with TestClient(demo_app) as client:
        response = client.post("/api/transcribe", content=b"x", headers={
            "Content-Length": str(MAX_AUDIO_BYTES + 1),
        })
        assert response.status_code == 413
        assert "Traceback" not in response.text
        assert "Body must not be read" not in response.text


@pytest.mark.xfail(strict=True, reason="Transcribe route exposes provider exceptions outside the allowed scope")
def test_transcribe_provider_error_is_safe(demo_app, monkeypatch):
    async def fail(*args):
        raise RuntimeError("private provider exception sentinel")

    monkeypatch.setattr(MissionService, "transcribe", fail)
    with TestClient(demo_app) as client:
        response = client.post("/api/transcribe", content=b"audio")
        assert response.status_code == 503
        assert "private provider exception sentinel" not in response.text
        assert "Traceback" not in response.text
