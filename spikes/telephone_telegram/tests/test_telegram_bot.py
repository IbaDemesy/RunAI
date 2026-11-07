"""Handlers Telegram testes sans token : faux transport Bot API (BaseRequest) qui enregistre chaque appel."""

import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
import telegram_bot
from gladia_prerecorded import Transcript
from orchestrator import MockOrchestrator
from telegram import Update
from telegram.request import BaseRequest

TOKEN = "123456:FAKE-TOKEN-FOR-TESTS"
CHAT = {"id": 4242, "type": "private", "first_name": "Camille"}
USER = {"id": 4242, "is_bot": False, "first_name": "Camille"}
OGG = b"OggS\x00fake-opus"


class FakeBotAPI(BaseRequest):
    def __init__(self):
        self.calls: list[tuple[str, dict, bool]] = []
        self._mid = 100

    @property
    def read_timeout(self):
        return None

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    def _message(self, extra=None):
        self._mid += 1
        return {"message_id": self._mid, "date": 0, "chat": CHAT, **(extra or {})}

    async def do_request(
        self,
        url,
        method,
        request_data=None,
        read_timeout=None,
        write_timeout=None,
        connect_timeout=None,
        pool_timeout=None,
    ):
        if "/file/bot" in url:
            self.calls.append(("download", {"url": url}, False))
            return 200, OGG
        name = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        multipart = bool(request_data and request_data.multipart_data)
        self.calls.append((name, params, multipart))
        result = {
            "getMe": {
                "id": 1,
                "is_bot": True,
                "first_name": "RunAI",
                "username": "runai_test_bot",
            },
            "getFile": {
                "file_id": "VOICE1",
                "file_unique_id": "u1",
                "file_size": len(OGG),
                "file_path": "voice/file_1.oga",
            },
            "answerCallbackQuery": True,
        }.get(name)
        if result is None:
            result = self._message(
                {"text": params.get("text", "")} if "text" in params else None
            )
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def markup(params):
    rm = params["reply_markup"]
    return json.loads(rm) if isinstance(rm, str) else rm


def message(**fields):
    return {"message_id": 1, "date": 0, "chat": CHAT, "from": USER, **fields}


@pytest.fixture
async def bot():
    api = FakeBotAPI()
    seen = []

    async def fake_transcribe(audio, **kwargs):
        seen.append((audio, kwargs))
        return Transcript(
            "Trouve-moi un semi en avril et prépare tout", "job-fake", 1.0, 2.0
        )

    app = telegram_bot.build_application(
        TOKEN,
        orchestrator=MockOrchestrator(step_delay=0),
        transcribe=fake_transcribe,
        request=api,
    )
    await app.initialize()
    app.seen_audio = seen
    yield app, api
    await app.shutdown()


async def feed(app, payload):
    await app.process_update(Update.de_json({"update_id": 1, **payload}, app.bot))
    await asyncio.gather(*app.bot_data.get("tasks", []))


async def test_voice_note_to_progress_and_validations(bot):
    app, api = bot
    await feed(
        app,
        {
            "message": message(
                voice={
                    "file_id": "VOICE1",
                    "file_unique_id": "u1",
                    "duration": 3,
                    "mime_type": "audio/ogg",
                }
            )
        },
    )

    assert api.named("getFile")[0][1]["file_id"] == "VOICE1"
    assert api.named("download")
    audio, kwargs = app.seen_audio[0]
    assert (
        audio == OGG
        and kwargs["content_type"] == "audio/ogg"
        and "semi" in kwargs["vocabulary"]
    )

    texts = [c[1]["text"] for c in api.named("sendMessage")]
    assert "J'ai compris" in texts[0] and "semi en avril" in texts[0]
    assert "mission m0001" in texts[1]
    progress_id = 102  # 101 = accuse de reception, 102 = message de suivi

    edits = api.named("editMessageText")
    assert len(edits) == 7 and all(e[1]["message_id"] == progress_id for e in edits)
    assert "✋ Hotel Accor" in edits[-1][1]["text"]

    photos = api.named("sendPhoto")
    assert len(photos) == 3 and all(
        p[2] for p in photos
    )  # multipart = vraie photo uploadee
    kb = markup(photos[0][1])
    labels = [b["text"] for row in kb["inline_keyboard"] for b in row]
    assert labels == ["Je valide", "Refuser", "Voir"]
    assert kb["inline_keyboard"][0][0]["callback_data"] == "ok|m0001|hotel"


def callback(data):
    return {
        "callback_query": {
            "id": "cb1",
            "from": USER,
            "chat_instance": "ci",
            "data": data,
            "message": message(
                caption="x",
                photo=[
                    {"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}
                ],
            ),
        }
    }


async def test_buttons_then_recap_documents(bot):
    app, api = bot
    await feed(app, {"message": message(text="Trouve-moi un semi en avril")})
    await feed(app, callback("see|m0001|hotel"))
    assert not api.named("editMessageCaption")
    await feed(app, callback("ok|m0001|hotel"))
    await feed(app, callback("no|m0001|transport"))
    assert not api.named("sendDocument")
    await feed(app, callback("ok|m0001|inscription"))

    mission = app.bot_data["orchestrator"].missions["m0001"]
    assert mission.decisions == {"hotel": True, "transport": False, "inscription": True}
    captions = [c[1]["caption"] for c in api.named("editMessageCaption")]
    assert "c'est toi qui paies" in captions[0] and "rien n'est soumis" in captions[1]
    docs = api.named("sendDocument")
    assert [d[1]["caption"] for d in docs] == [
        "Récap du week-end",
        "À ajouter à ton agenda",
        "Parcours (GPX)",
    ]
    assert all(d[2] for d in docs)
    assert len(api.named("answerCallbackQuery")) == 4


async def test_unknown_mission_alert(bot):
    app, api = bot
    await feed(app, callback("ok|m9999|hotel"))
    assert api.named("answerCallbackQuery")[0][1]["show_alert"] is True


async def test_start_location_keyboard_and_miniapp(bot, monkeypatch):
    app, api = bot
    monkeypatch.setenv("RUNAI_PWA_URL", "https://runai.example/app")
    await feed(
        app,
        {
            "message": message(
                text="/start",
                entities=[{"type": "bot_command", "offset": 0, "length": 6}],
            )
        },
    )
    sent = api.named("sendMessage")
    kb = markup(sent[0][1])
    assert kb["keyboard"][0][0]["request_location"] is True
    mini = markup(sent[1][1])
    assert (
        mini["inline_keyboard"][0][0]["web_app"]["url"] == "https://runai.example/app"
    )


def test_miniapp_requires_https(monkeypatch):
    monkeypatch.setenv("RUNAI_PWA_URL", "http://localhost:5173")
    assert telegram_bot.miniapp_markup() is None
    monkeypatch.setenv("RUNAI_PWA_URL", "https://runai.example/app?x=1")
    url = telegram_bot.miniapp_markup("m0001").inline_keyboard[0][0].web_app.url
    assert url == "https://runai.example/app?x=1&mission=m0001"


async def test_location_share(bot):
    app, api = bot
    await feed(
        app, {"message": message(location={"latitude": 48.8566, "longitude": 2.3522})}
    )
    assert "48.8566, 2.3522" in api.named("sendMessage")[0][1]["text"]


async def test_webapp_data(bot):
    app, api = bot
    await feed(
        app,
        {
            "message": message(
                web_app_data={
                    "data": json.dumps({"action": "validate"}),
                    "button_text": "RunAI",
                }
            )
        },
    )
    assert "validate" in api.named("sendMessage")[0][1]["text"]


def test_validate_init_data():
    fields = {
        "auth_date": "1700000000",
        "query_id": "AAH",
        "user": json.dumps({"id": 4242, "first_name": "Camille"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    good = urlencode(
        {**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}
    )
    assert telegram_bot.validate_init_data(good, TOKEN)["query_id"] == "AAH"
    assert telegram_bot.validate_init_data(good.replace("4242", "4243"), TOKEN) is None
    assert telegram_bot.validate_init_data(good, "999:OTHER") is None
