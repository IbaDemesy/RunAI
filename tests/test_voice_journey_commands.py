import pytest
from pydantic import ValidationError

from runai.contracts.journey import ChapterId
from runai.voice.journey_commands import build_voice_reply, parse_journey_command


@pytest.mark.parametrize(
    ("text", "target", "action"),
    [
        ("pause", "agents", "pause"),
        ("mets en pause les agents", "agents", "pause"),
        ("agents pause", "agents", "pause"),
        ("PAUSE CAMÉRA!", "camera", "pause"),
        ("arrête la caméra", "camera", "pause"),
        ("stop the camera", "camera", "pause"),
        ("reprends", "agents", "resume"),
        ("continue", "agents", "resume"),
        ("resume the agents", "agents", "resume"),
        ("reprends le survol", "camera", "play"),
        ("reprends la caméra", "camera", "play"),
        ("play the camera", "camera", "play"),
    ],
)
def test_targeted_controls(text, target, action):
    command = parse_journey_command(text)
    assert (command.target, command.action) == (target, action)


@pytest.mark.parametrize(
    ("text", "chapter"),
    [
        ("voir la maison", ChapterId.home),
        ("montre la gare", ChapterId.departure_hub),
        ("montre le trajet", ChapterId.main_transport),
        ("voir l'hôtel", ChapterId.arrival_hotel),
        ("voir le dossard", ChapterId.bib_pickup),
        ("la course", ChapterId.race),
        ("montre le retour", ChapterId.return_trip),
        ("show the hotel", ChapterId.arrival_hotel),
        ("show me the race", ChapterId.race),
    ],
)
def test_chapters(text, chapter):
    command = parse_journey_command(text)
    assert command.action == "show_chapter"
    assert command.chapter_id is chapter


@pytest.mark.parametrize(
    ("text", "km"),
    [
        ("km 30", 30),
        ("va au kilomètre 21,5", 21.5),
        ("kilometer 10", 10),
        ("km 0", 0),
        ("go to kilometer 10.5", 10.5),
    ],
)
def test_seek(text, km):
    command = parse_journey_command(text)
    assert command.action == "seek_km"
    assert command.seek_km == km


@pytest.mark.parametrize(
    "text",
    [
        "",
        "bonjour",
        "je veux un hôtel",
        "ne mets pas en pause les agents",
        "don't pause",
        "km -1",
        "km NaN",
        "km inf",
        "je cours 30 km",
        "pause puis annule",
        "un hôtel à 100 euros",
    ],
)
def test_free_text(text):
    assert parse_journey_command(text) is None


def test_voice_reply():
    reply = build_voice_reply("Je pars de chez moi", revision=7)
    assert reply.model_dump(exclude_none=True) == {
        "revision": 7,
        "text": "Je pars de chez moi",
        "channel": "voice",
        "corrections": {},
    }
    assert build_voice_reply("", 8).text == ""
    with pytest.raises(ValidationError):
        build_voice_reply("x" * 1001, 7)
