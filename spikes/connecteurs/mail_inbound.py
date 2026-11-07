"""Réponse entrante par e-mail -> message dans une session H (non testé avec de vraies clés).

Chaîne : le coureur répond au récap -> Resend Inbound (adresse runai+<session_h>@<id>.resend.app)
-> webhook `email.received` signé (Svix) -> GET /emails/receiving/{id} (le webhook ne contient pas
le corps) -> nettoyage de la citation -> `send_session_messages` sur la session H.

Variables : RESEND_WEBHOOK_SECRET (whsec_...), RESEND_API_KEY, HAI_API_KEY.
    python mail_inbound.py --port 8787     # POST /webhooks/resend
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

TOLERANCE_S = 300
LONGUEUR_MAX = 2000
CONSIGNE = ("[Réponse du coureur par e-mail, transmise par RunAI] Applique cette correction si elle "
            "concerne ta mission. Ne paie rien et ne soumets rien de définitif. Message : ")


class SignatureInvalide(Exception):
    pass


def verifier_svix(secret: str, entetes: dict[str, str], corps: bytes, maintenant: float | None = None) -> None:
    e = {k.lower(): v for k, v in entetes.items()}
    msg_id, ts, sigs = e.get("svix-id"), e.get("svix-timestamp"), e.get("svix-signature")
    if not (msg_id and ts and sigs):
        raise SignatureInvalide("en-têtes svix manquants")
    if abs((maintenant or time.time()) - int(ts)) > TOLERANCE_S:
        raise SignatureInvalide("horodatage hors tolérance")
    cle = base64.b64decode(secret.removeprefix("whsec_"))
    attendu = base64.b64encode(hmac.new(cle, f"{msg_id}.{ts}.".encode() + corps, hashlib.sha256).digest()).decode()
    if not any(hmac.compare_digest(attendu, s.split(",", 1)[-1]) for s in sigs.split()):
        raise SignatureInvalide("signature invalide")


def session_depuis_destinataires(destinataires: list[str]) -> str | None:
    for adresse in destinataires:
        m = re.search(r"\+([A-Za-z0-9_-]+)@", adresse)
        if m:
            return m.group(1)
    return None


def texte_utile(texte: str) -> str:
    utile = []
    for ligne in texte.replace("\r\n", "\n").split("\n"):
        if ligne.startswith(">") or re.match(r"^(Le .+ a écrit|On .+ wrote)\s*:?\s*$", ligne.strip()):
            break
        if ligne.strip() in ("--", "-- "):
            break
        utile.append(ligne)
    return "\n".join(utile).strip()[:LONGUEUR_MAX]


def lire_email_recu(email_id: str, cle: str) -> dict:
    r = httpx.get(f"https://api.resend.com/emails/receiving/{email_id}",
                  headers={"Authorization": f"Bearer {cle}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def envoyer_a_h(session_id: str, texte: str) -> None:
    from hai_agents import Client, SendSessionMessagesRequestBody_UserMessage

    Client().sessions.send_session_messages(
        session_id, request=SendSessionMessagesRequestBody_UserMessage(message=CONSIGNE + texte))


def traiter(corps: bytes, entetes: dict[str, str], secret: str,
            lire: Callable[[str], dict], envoyer: Callable[[str, str], None],
            sessions_autorisees: set[str] | None = None) -> dict:
    verifier_svix(secret, entetes, corps)
    evt = json.loads(corps)
    if evt.get("type") != "email.received":
        return {"ignore": evt.get("type")}
    data = evt["data"]
    session_id = session_depuis_destinataires(data.get("to", []))
    if not session_id or (sessions_autorisees is not None and session_id not in sessions_autorisees):
        return {"ignore": "session inconnue"}
    complet = lire(data["email_id"])
    texte = texte_utile(complet.get("text") or re.sub(r"<[^>]+>", " ", complet.get("html") or ""))
    if not texte:
        return {"ignore": "corps vide"}
    envoyer(session_id, texte)
    return {"session_id": session_id, "transmis": texte}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8787)
    a = p.parse_args()
    secret, cle = os.environ["RESEND_WEBHOOK_SECRET"], os.environ["RESEND_API_KEY"]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            corps = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                res = traiter(corps, dict(self.headers), secret, lambda i: lire_email_recu(i, cle), envoyer_a_h)
                code = 200
            except SignatureInvalide as exc:
                res, code = {"erreur": str(exc)}, 401
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode())

    HTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
