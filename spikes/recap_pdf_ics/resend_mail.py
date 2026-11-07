"""Option mail (prepare, non branche a une vraie cle).

Sortant : POST https://api.resend.com/emails avec le PDF et le .ics en pieces jointes (base64).
Entrant : webhook Resend `email.received` (signe Svix) -> GET /emails/receiving/{email_id} pour le texte
          -> nettoyage de la citation -> POST {H}/sessions/{id}/messages (send_message) sur la bonne mission.

Variables (aucune n'est requise pour les tests : sans cle tout passe en dry-run) :
  RESEND_API_KEY        re_...  (cle API Resend, scope "sending" + lecture receiving)
  RESEND_FROM           ex. "RunAI <recap@mail.runai.example>"  (domaine d'envoi verifie SPF/DKIM)
  RESEND_INBOUND_DOMAIN ex. "xxxx.resend.app" (domaine Resend) ou "in.runai.example" (MX vers Resend)
  RESEND_WEBHOOK_SECRET whsec_...  (secret de signature du webhook email.received)
  HAI_API_KEY           cle H (deja disponible)
  H_SEND_ENABLED=1      sinon le relais vers H reste en dry-run (un send_message sur une session terminee
                        la relance : facturation + 1 slot du quota)
"""

import base64
import os
import re

import httpx
from svix.webhooks import Webhook, WebhookVerificationError

from models import Recap

RESEND_API = "https://api.resend.com"
H_API = os.environ.get("H_API_BASE", "https://agp.eu.hcompany.ai/api/v2")
GUARDRAIL = "Rappel RunAI : ne paie rien, ne soumets rien, arrete-toi avant la page de paiement. Message de l'utilisateur : "


def reply_address(recap_id: str) -> str | None:
    dom = os.environ.get("RESEND_INBOUND_DOMAIN")
    return f"runai+{recap_id}@{dom}" if dom else None


def build_email(r: Recap, pdf: bytes, ics: bytes, to: str) -> dict:
    lines = [f"<li><b>{m.title}</b> : {'prêt, à payer' if m.status == 'pret_a_payer' else m.status}"
             + (f" — <a href=\"{m.finalize_url}\">{m.finalize_label}</a>" if m.finalize_url else "") + "</li>"
             for m in r.missions]
    payload = {
        "from": os.environ.get("RESEND_FROM", "RunAI <onboarding@resend.dev>"),
        "to": [to],
        "subject": f"Ton week-end {r.race_name} est prêt (à payer)",
        "html": (f"<p>Bonjour {r.runner.full_name.split()[0]},</p><p>Tes missions sont prêtes. "
                 "Rien n'est payé : chaque agent s'est arrêté avant le paiement.</p>"
                 f"<ul>{''.join(lines)}</ul><p>Total estimé : {r.total_eur:.2f} €. Le récap PDF et l'agenda .ics sont joints.</p>"
                 "<p>Réponds à ce mail pour donner une consigne à un agent (ex. « hôtel : prends la chambre avec petit-déjeuner »).</p>"),
        "attachments": [
            {"filename": f"RunAI_recap_{r.id}.pdf", "content": base64.b64encode(pdf).decode(), "content_type": "application/pdf"},
            {"filename": "week-end.ics", "content": base64.b64encode(ics).decode(), "content_type": "text/calendar; charset=utf-8; method=PUBLISH"},
        ],
        "tags": [{"name": "recap_id", "value": re.sub(r"[^A-Za-z0-9_-]", "_", r.id)}],
    }
    if reply := reply_address(r.id):
        payload["reply_to"] = reply
    return payload


def send_recap(r: Recap, pdf: bytes, ics: bytes, to: str, client: httpx.Client | None = None) -> dict:
    payload = build_email(r, pdf, ics, to)
    key = os.environ.get("RESEND_API_KEY")
    size = sum(len(a["content"]) for a in payload["attachments"])
    if not key:
        return {"dry_run": True, "reason": "RESEND_API_KEY absente", "attachments_b64_bytes": size,
                "payload": {k: v for k, v in payload.items() if k != "attachments"} | {"attachments": [a["filename"] for a in payload["attachments"]]}}
    c = client or httpx.Client(timeout=30)
    resp = c.post(f"{RESEND_API}/emails", json=payload, headers={"Authorization": f"Bearer {key}"})
    resp.raise_for_status()
    return {"dry_run": False, "id": resp.json().get("id"), "attachments_b64_bytes": size}


def verify_webhook(body: bytes, headers: dict) -> dict:
    secret = os.environ.get("RESEND_WEBHOOK_SECRET")
    if not secret:
        raise PermissionError("RESEND_WEBHOOK_SECRET absente : webhook refuse")
    h = {k.lower(): v for k, v in headers.items()}
    try:
        return Webhook(secret).verify(body, {k: h.get(k, "") for k in ("svix-id", "svix-timestamp", "svix-signature")})
    except WebhookVerificationError as e:
        raise PermissionError(f"signature invalide: {e}") from e


_QUOTE = re.compile(r"^(>|Le .+ a écrit\s*:|On .+ wrote:|-----Original Message-----|De ?: )", re.I)


def strip_quoted(text: str) -> str:
    out = []
    for line in (text or "").splitlines():
        if _QUOTE.match(line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()


KEYWORDS = {"hotel": ("hôtel", "hotel", "chambre", "nuit", "accor", "ibis"),
            "transport": ("vol", "train", "avion", "transport", "billet", "tap"),
            "inscription": ("inscription", "dossard", "course", "semi")}


def route_mission(r: Recap, text: str):
    low = text.lower()
    with_session = [m for m in r.missions if m.run.session_id]
    for m in with_session:
        if any(re.search(rf"\b{re.escape(k)}\b", low) for k in KEYWORDS[m.key]):
            return m
    return with_session[0] if with_session else None


def recap_id_from_to(addresses: list[str]) -> str | None:
    for a in addresses:
        if m := re.search(r"runai\+([A-Za-z0-9_-]+)@", a):
            return m.group(1)
    return None


def handle_inbound(event: dict, get_recap, resend: httpx.Client | None = None, h: httpx.Client | None = None) -> dict:
    if event.get("type") != "email.received":
        return {"ignored": event.get("type")}
    data = event["data"]
    recap_id = recap_id_from_to(data.get("to", []))
    r = get_recap(recap_id) if recap_id else None
    if r is None:
        return {"error": "recap inconnu", "to": data.get("to")}
    if r.runner.email and data.get("from", "").lower() != r.runner.email.lower():
        return {"error": "expediteur non autorise", "from": data.get("from")}
    key = os.environ.get("RESEND_API_KEY")
    if key:
        c = resend or httpx.Client(timeout=20)
        full = c.get(f"{RESEND_API}/emails/receiving/{data['email_id']}", headers={"Authorization": f"Bearer {key}"})
        full.raise_for_status()
        body = full.json()
        text = body.get("text") or re.sub(r"<[^>]+>", " ", body.get("html") or "")
    else:
        text = data.get("text", "")
    text = strip_quoted(text)
    if not text:
        return {"error": "reponse vide"}
    m = route_mission(r, text)
    if m is None:
        return {"error": "aucune session H a relayer"}
    msg = {"type": "user_message", "message": GUARDRAIL + text}
    out = {"recap_id": r.id, "mission": m.key, "session_id": m.run.session_id, "message": msg["message"]}
    if os.environ.get("H_SEND_ENABLED") != "1" or not os.environ.get("HAI_API_KEY"):
        return out | {"dry_run": True}
    c = h or httpx.Client(timeout=20)
    resp = c.post(f"{H_API}/sessions/{m.run.session_id}/messages", json=msg,
                  headers={"Authorization": f"Bearer {os.environ['HAI_API_KEY']}"})
    resp.raise_for_status()
    return out | {"dry_run": False, "h_status": resp.status_code}
