"""Canal telephone sans Twilio ni Gladia : faux STT et faux TTS injectes, faux flux Media Streams via TestClient."""

import asyncio
import base64
import json

import phone_server
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from gladia_live import LiveEvent, parse_message, telephone_config
from tts import TTSResult

SID = "MZ" + "1" * 32


class FakeSTT:
    """Renvoie un transcript final pour chaque bloc d'audio non silencieux puis silence (>= 0,2 s)."""

    def __init__(self, script):
        self.script = list(script)
        self.events: asyncio.Queue = asyncio.Queue()
        self.audio = bytearray()
        self.started = self.closed = False

    async def start(self):
        self.started = True

    async def send_audio(self, chunk):
        self.audio += chunk
        if chunk == b"\x01" * 160 and self.script:
            item = self.script.pop(0)
            kind, text = item if isinstance(item, tuple) else ("final", item)
            await self.events.put(LiveEvent(kind, text, 0.0))

    async def close(self):
        self.closed = True
        await self.events.put(LiveEvent("closed", "", 0.0))


class FakeTTS:
    def __init__(self):
        self.texts = []

    async def asynthesize(self, text):
        self.texts.append(text)
        return TTSResult(b"\x7f" * 8000, 1.0, 1.0, 1.0)  # 1 s d'audio par phrase


def start_msg():
    return {
        "event": "start",
        "start": {
            "streamSid": SID,
            "callSid": "CA1",
            "mediaFormat": {
                "encoding": "audio/x-mulaw",
                "sampleRate": 8000,
                "channels": 1,
            },
            "customParameters": {"caller": "+33600000000"},
        },
    }


def media(byte=b"\x01"):
    return {
        "event": "media",
        "media": {"track": "inbound", "payload": base64.b64encode(byte * 160).decode()},
    }


def collect_until_mark(ws):
    msgs = []
    while True:
        m = json.loads(ws.receive_text())
        msgs.append(m)
        if m["event"] == "mark":
            return msgs


def make(script):
    stt = FakeSTT(script)
    tts = FakeTTS()
    app = phone_server.create_app(stt_factory=lambda: stt, tts=tts)
    return app, stt, tts


def test_full_call_confirm_launch_and_hangup():
    app, stt, tts = make(["Trouve-moi un semi en avril et prépare tout", "oui vas-y"])
    with TestClient(app) as client, client.websocket_connect("/twilio/media") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(start_msg())
        ws.send_json(media())
        out = collect_until_mark(ws) + collect_until_mark(ws)  # 2 phrases -> 2 marks
        assert {m["streamSid"] for m in out} == {SID}
        assert (
            sum(
                len(base64.b64decode(m["media"]["payload"]))
                for m in out
                if m["event"] == "media"
            )
            == 16000
        )
        assert "semi-marathon en avril" in tts.texts[0]
        for _ in range(2):
            ws.send_json({"event": "mark", "mark": {"name": "turn1"}})
        ws.send_json(media())
        for _ in range(5):  # 5 phrases dans le message final -> 5 marks
            collect_until_mark(ws)
        assert "je t'envoie tout par message" in " ".join(tts.texts)
        for _ in range(5):
            ws.send_json({"event": "mark", "mark": {"name": "turn2"}})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()  # le serveur ferme le flux : Twilio raccroche
    assert stt.started and stt.closed and len(stt.audio) == 320
    assert app.state.notifier.sent == [("+33600000000", "m0001")]
    assert app.state.orchestrator.missions["m0001"].channel == "phone"


def test_barge_in_sends_clear():
    app, _stt, _tts = make(["Trouve-moi un marathon en mai", ("speech_start", "")])
    with TestClient(app) as client, client.websocket_connect("/twilio/media") as ws:
        ws.send_json(start_msg())
        ws.send_json(media())
        collect_until_mark(ws)
        ws.send_json(media())  # l'appelant reparle pendant que RunAI parle
        msgs = []
        while not msgs or msgs[-1]["event"] != "clear":
            msgs.append(json.loads(ws.receive_text()))
        assert msgs[-1] == {"event": "clear", "streamSid": SID}
        ws.send_json({"event": "stop"})


def test_outbound_track_ignored_and_missing_distance():
    app, stt, tts = make(["Prépare tout pour avril"])
    with TestClient(app) as client, client.websocket_connect("/twilio/media") as ws:
        ws.send_json(start_msg())
        ws.send_json(
            {
                "event": "media",
                "media": {
                    "track": "outbound",
                    "payload": base64.b64encode(b"\x01" * 160).decode(),
                },
            }
        )
        ws.send_json(media())
        collect_until_mark(ws)
        ws.send_json({"event": "stop"})
    assert len(stt.audio) == 160
    assert tts.texts[0].startswith("Quelle distance")


def test_voice_twiml_and_signature(monkeypatch):
    app, _, _ = make([])
    client = TestClient(app)
    monkeypatch.setenv("PUBLIC_HOST", "runai.example.com")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-auth-token")
    form = {"CallSid": "CA1", "From": "+33600000000", "To": "+33100000000"}
    url = "http://testserver/twilio/voice"
    assert client.post("/twilio/voice", data=form).status_code == 403
    sig = phone_server.twilio_signature("fake-auth-token", url, form)
    r = client.post("/twilio/voice", data=form, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and r.headers["content-type"].startswith(
        "application/xml"
    )
    assert '<Connect><Stream url="wss://runai.example.com/twilio/media">' in r.text
    assert (
        '<Parameter name="caller" value="+33600000000"/>' in r.text and "<Say" in r.text
    )


def test_twilio_signature_reference_vector():
    # Exemple de la doc Twilio (twilio.com/docs/usage/security), valeur recoupee avec twilio.request_validator 9.13.0
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    sig = phone_server.twilio_signature(
        "12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params
    )
    assert sig == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_gladia_config_and_parse():
    cfg = telephone_config(endpointing=0.1)
    assert (cfg["encoding"], cfg["sample_rate"], cfg["bit_depth"], cfg["channels"]) == (
        "wav/ulaw",
        8000,
        8,
        1,
    )
    ev = parse_message(
        {
            "type": "transcript",
            "data": {"is_final": True, "utterance": {"text": " Bonjour "}},
        },
        1.0,
    )
    assert (ev.kind, ev.text) == ("final", "Bonjour")
    assert parse_message({"type": "speech_start"}, 0).kind == "speech_start"


def test_split_sentences():
    assert phone_server.split_sentences("C'est parti. Je m'en occupe ! Ok ?") == [
        "C'est parti.",
        "Je m'en occupe !",
        "Ok ?",
    ]
