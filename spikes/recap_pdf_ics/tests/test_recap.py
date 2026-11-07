import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from svix.webhooks import Webhook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api  # noqa: E402
import ics_export  # noqa: E402
import render  # noqa: E402
import resend_mail  # noqa: E402
import samples  # noqa: E402

SECRET = "whsec_" + base64.b64encode(b"test-secret-runai-0123456789abcd").decode()


@pytest.fixture(scope="module")
def client():
    with TestClient(api.app) as c:
        yield c


@pytest.mark.parametrize("rid", list(samples.RECAPS))
def test_html_vocabulary(rid):
    html = render.render_html(samples.get_recap(rid)).lower()
    assert "réservé" not in html and "reserve" not in html
    assert "à payer" in html and "agent arrêté ici" in html


@pytest.mark.parametrize("rid", list(samples.RECAPS))
def test_pdf_endpoint(client, rid):
    r = client.get(f"/recap/{rid}.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    assert doc.page_count == 3
    assert "Ton week-end de course est prêt" in text and "AGENT ARRÊTÉ ICI" in text
    assert float(r.headers["X-Gen-Ms"]) < 5000


def test_pdf_weasyprint(client):
    r = client.get("/recap/demo-nantes.pdf?engine=weasyprint")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"


@pytest.mark.parametrize("rid", list(samples.RECAPS))
def test_ics_endpoint(client, rid):
    r = client.get(f"/recap/{rid}.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    v = ics_export.validate_ics(r.content)
    assert v["vtimezone"] == ["Europe/Paris"] and v["dtstart_tzids"] == ["Europe/Paris"]
    assert v["crlf_only"] and v["max_line_octets"] <= 75 and v["uids_unique"]
    assert v["events"] == v["vobject_events"] >= 4


def test_ics_has_required_events():
    v = ics_export.validate_ics(ics_export.build_ics(samples.get_recap("demo-nantes")))
    s = " ".join(v["summaries"]).lower()
    assert "dossard" in s and "départ du semi" in s and s.count("train") == 2


def test_404(client):
    assert client.get("/recap/inconnu.pdf").status_code == 404


def test_send_dry_run(client, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_INBOUND_DOMAIN", "demo.resend.app")
    r = client.post("/recap/lisbonne-h/send", params={"to": "camille.martin@example.com"}).json()
    assert r["dry_run"] and r["payload"]["attachments"] == ["RunAI_recap_lisbonne-h.pdf", "week-end.ics"]
    assert r["payload"]["reply_to"] == "runai+lisbonne-h@demo.resend.app"
    assert "réservé" not in json.dumps(r, ensure_ascii=False)


def test_send_with_key_mocked(monkeypatch):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"id": "email_123"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    r = samples.get_recap("demo-nantes")
    out = resend_mail.send_recap(r, b"%PDF-1.7 x", b"BEGIN:VCALENDAR", "camille.martin@example.com",
                                 client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == {"dry_run": False, "id": "email_123", "attachments_b64_bytes": out["attachments_b64_bytes"]}
    assert base64.b64decode(seen["body"]["attachments"][0]["content"]) == b"%PDF-1.7 x"
    assert seen["auth"] == "Bearer re_test"


def _signed(payload: dict):
    body = json.dumps(payload)
    ts = datetime.now(timezone.utc)
    sig = Webhook(SECRET).sign("msg_1", ts, body)
    return body, {"svix-id": "msg_1", "svix-timestamp": str(int(ts.timestamp())), "svix-signature": sig}


EVENT = {"type": "email.received", "data": {"email_id": "em_1", "from": "camille.martin@example.com",
         "to": ["runai+lisbonne-h@demo.resend.app"], "subject": "Re: Ton week-end",
         "text": "Pour l'hôtel prends le petit-déjeuner.\n\nLe sam. 7 nov. 2026, RunAI a écrit :\n> blabla"}}


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    body, h = _signed(EVENT)
    h["svix-signature"] = "v1,AAAA"
    assert client.post("/webhooks/resend", content=body, headers=h).status_code == 401


def test_webhook_routes_to_h_session_dry_run(client, monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("H_SEND_ENABLED", raising=False)
    body, h = _signed(EVENT)
    r = client.post("/webhooks/resend", content=body, headers=h).json()
    assert r["dry_run"] and r["mission"] == "hotel"
    assert r["session_id"] == "ea01ea80-ea2a-4efb-8885-8c123acc509a"
    assert r["message"].endswith("Pour l'hôtel prends le petit-déjeuner.")


def test_inbound_full_chain_mocked(monkeypatch):
    calls = []

    def handler(req):
        calls.append((req.method, str(req.url), req.content))
        if "resend" in req.url.host:
            return httpx.Response(200, json={"text": "Le vol : garde le tarif Discount.\n> cite", "html": None})
        return httpx.Response(202)

    mock = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("HAI_API_KEY", "hk_test")
    monkeypatch.setenv("H_SEND_ENABLED", "1")
    ev = json.loads(json.dumps(EVENT))
    ev["data"].pop("text")
    out = resend_mail.handle_inbound(ev, samples.get_recap, resend=mock, h=mock)
    assert out["mission"] == "transport" and out["h_status"] == 202
    assert calls[0][1] == "https://api.resend.com/emails/receiving/em_1"
    assert calls[1][1].endswith("/sessions/d659ae18-6faa-4681-8e90-60bcee1d1db2/messages")
    assert json.loads(calls[1][2])["message"].endswith("Le vol : garde le tarif Discount.")


def test_inbound_rejects_unknown_sender():
    ev = json.loads(json.dumps(EVENT))
    ev["data"]["from"] = "attacker@example.org"
    assert resend_mail.handle_inbound(ev, samples.get_recap)["error"] == "expediteur non autorise"
