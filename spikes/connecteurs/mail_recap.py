"""Envoi du récap RunAI (PDF + .ics) par e-mail : dry-run .eml, Resend, Brevo ou SMTP (Gmail).

Sans `--envoyer`, rien ne part : le message est écrit en .eml puis relu et validé.
Variables : RESEND_API_KEY, BREVO_API_KEY, SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD, MAIL_FROM.

    python mail_recap.py                       # dry-run, écrit out/recap.eml
    python mail_recap.py --backend resend --to delivered@resend.dev --envoyer
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from pathlib import Path
from string import Template

import httpx
from agenda_ics import construire_ics, evenements_week_end
from minipdf import make_pdf

ICI = Path(__file__).parent
LIMITE_RESEND_OCTETS = 40 * 1024 * 1024

HTML = Template("""<!doctype html><html lang="fr"><body style="font-family:Arial,sans-serif;color:#111">
<h2 style="margin:0 0 8px">Ton week-end : $course</h2>
<p>Bonjour $prenom, voici ce que RunAI a préparé. <b>Rien n'a été payé ni réservé</b> :
c'est toi qui signes et paies, sur chaque site.</p>
<table cellpadding="6" style="border-collapse:collapse;border:1px solid #ddd">$lignes</table>
<p>En pièces jointes : le récap PDF et <b>weekend.ics</b> (ouvre-le pour ajouter le week-end à ton agenda).</p>
<p style="color:#666;font-size:12px">Tu peux répondre à cet e-mail pour corriger une mission en cours.</p>
</body></html>""")


def _cout(c: dict) -> str:
    if c.get("montant_eur") is None:
        return "à lire par l'agent"
    return f"{c['montant_eur']:.2f} €" + ("" if c.get("mesure") else " (estimé)")


def corps(recap: dict) -> tuple[str, str]:
    prenom = recap["coureur"]["nom"].split()[0]
    couts = recap.get("couts", [])
    texte = [f"Bonjour {prenom},", "", f"Ton week-end : {recap['nom_course']}.",
             "Rien n'a été payé ni réservé : c'est toi qui signes et paies.", ""]
    texte += [f"- {c['poste']} : {_cout(c)}" for c in couts]
    texte += ["", "Pièces jointes : recap.pdf, weekend.ics."]
    lignes = "".join(f"<tr><td style='border:1px solid #ddd'>{c['poste']}</td>"
                     f"<td style='border:1px solid #ddd'>{_cout(c)}</td></tr>" for c in couts)
    return "\n".join(texte), HTML.substitute(course=recap["nom_course"], prenom=prenom, lignes=lignes)


def pieces_jointes(recap: dict) -> list[tuple[str, str, bytes]]:
    pdf = make_pdf(f"RunAI - {recap['nom_course']}",
                   [f"{c['poste']} : {_cout(c)}" for c in recap.get("couts", [])]
                   + ["", "Aucun paiement ni réservation effectué par RunAI."])
    ics = construire_ics(evenements_week_end(recap)).encode("utf-8")
    return [("recap.pdf", "application/pdf", pdf), ("weekend.ics", "text/calendar", ics)]


def construire_message(recap: dict, expediteur: str, destinataire: str, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = expediteur
    msg["To"] = destinataire
    msg["Subject"] = f"RunAI : ton week-end {recap['nom_course']} est prêt (à valider)"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=expediteur.rsplit("@", 1)[-1].strip(">"))
    if reply_to:
        msg["Reply-To"] = reply_to
    texte, html = corps(recap)
    msg.set_content(texte)
    msg.add_alternative(html, subtype="html")
    for nom, mime, data in pieces_jointes(recap):
        maintype, subtype = mime.split("/")
        params = {"method": "PUBLISH"} if subtype == "calendar" else {}
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=nom, params=params)
    return msg


def valider_eml(brut: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(brut)
    erreurs = [h for h in ("From", "To", "Subject", "Date", "Message-ID") if not msg[h]]
    if msg.get_content_type() != "multipart/mixed":
        erreurs.append(f"type racine {msg.get_content_type()}")
    pj = {p.get_filename(): p for p in msg.iter_attachments()}
    if not pj.get("recap.pdf") or not pj["recap.pdf"].get_content().startswith(b"%PDF-"):
        erreurs.append("recap.pdf absent ou invalide")
    ics = pj.get("weekend.ics")
    contenu_ics = ics.get_content() if ics else ""
    if isinstance(contenu_ics, bytes):
        contenu_ics = contenu_ics.decode("utf-8")
    if not contenu_ics.startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in contenu_ics:
        erreurs.append("weekend.ics absent ou invalide")
    corps_html = msg.get_body(("html",))
    corps_txt = msg.get_body(("plain",))
    if not corps_html or not corps_txt:
        erreurs.append("il faut une version texte et une version HTML")
    taille_b64 = sum(len(base64.b64encode(p.get_content() if isinstance(p.get_content(), bytes)
                                          else p.get_content().encode())) for p in pj.values())
    return {"ok": not erreurs, "erreurs": erreurs, "taille_octets": len(brut),
            "pieces_jointes": sorted(pj), "nb_vevent": contenu_ics.count("BEGIN:VEVENT"),
            "sous_limite_resend_40mo": len(brut) < LIMITE_RESEND_OCTETS and taille_b64 < LIMITE_RESEND_OCTETS}


def _parties(msg: EmailMessage) -> tuple[str, str, list[tuple[str, str, bytes]]]:
    texte = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    pj = []
    for p in msg.iter_attachments():
        c = p.get_content()
        pj.append((p.get_filename(), p.get_content_type(), c if isinstance(c, bytes) else c.encode()))
    return texte, html, pj


def payload_resend(msg: EmailMessage) -> dict:
    texte, html, pj = _parties(msg)
    data = {"from": msg["From"], "to": [msg["To"]], "subject": msg["Subject"], "text": texte, "html": html,
            "attachments": [{"filename": n, "content": base64.b64encode(d).decode(), "content_type": m}
                            for n, m, d in pj]}
    if msg["Reply-To"]:
        data["reply_to"] = msg["Reply-To"]
    return data


def payload_brevo(msg: EmailMessage) -> dict:
    texte, html, pj = _parties(msg)
    data = {"sender": {"email": msg["From"]}, "to": [{"email": msg["To"]}], "subject": msg["Subject"],
            "textContent": texte, "htmlContent": html,
            "attachment": [{"name": n, "content": base64.b64encode(d).decode()} for n, _, d in pj]}
    if msg["Reply-To"]:
        data["replyTo"] = {"email": msg["Reply-To"]}
    return data


def envoyer_resend(msg: EmailMessage, cle: str) -> str:
    r = httpx.post("https://api.resend.com/emails", json=payload_resend(msg),
                   headers={"Authorization": f"Bearer {cle}"}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def envoyer_brevo(msg: EmailMessage, cle: str) -> str:
    r = httpx.post("https://api.brevo.com/v3/smtp/email", json=payload_brevo(msg),
                   headers={"api-key": cle, "accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json().get("messageId", "")


def envoyer_smtp(msg: EmailMessage, hote: str, port: int, user: str, mot_de_passe: str) -> str:
    with smtplib.SMTP(hote, port, timeout=30) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(user, mot_de_passe)
        s.send_message(msg)
    return msg["Message-ID"]


def backend_auto() -> str:
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("BREVO_API_KEY"):
        return "brevo"
    if os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"):
        return "smtp"
    return "dryrun"


def main() -> None:
    p = argparse.ArgumentParser(description="Envoi du récap RunAI")
    p.add_argument("--recap", default=str(ICI / "fixtures/recap_weekend.json"))
    p.add_argument("--backend", choices=["auto", "dryrun", "resend", "brevo", "smtp"], default="auto")
    p.add_argument("--to", default=None, help="défaut : e-mail fictif du récap")
    p.add_argument("--reply-to", default=os.getenv("MAIL_REPLY_TO"))
    p.add_argument("--envoyer", action="store_true", help="sans ce drapeau, rien ne part")
    p.add_argument("--out", default=str(ICI / "out"))
    a = p.parse_args()
    recap = json.loads(Path(a.recap).read_text(encoding="utf-8"))
    backend = backend_auto() if a.backend == "auto" else a.backend
    expediteur = os.getenv("MAIL_FROM") or ("RunAI <onboarding@resend.dev>" if backend == "resend"
                                            else "RunAI <runai@example.com>")
    msg = construire_message(recap, expediteur, a.to or recap["coureur"]["email"], a.reply_to)
    Path(a.out).mkdir(exist_ok=True)
    eml = Path(a.out) / "recap.eml"
    eml.write_bytes(msg.as_bytes(policy=policy.SMTP))
    resultat = {"backend": backend, "eml": str(eml), "validation": valider_eml(eml.read_bytes())}
    if a.envoyer and backend != "dryrun":
        if backend == "resend":
            resultat["id"] = envoyer_resend(msg, os.environ["RESEND_API_KEY"])
        elif backend == "brevo":
            resultat["id"] = envoyer_brevo(msg, os.environ["BREVO_API_KEY"])
        else:
            resultat["id"] = envoyer_smtp(msg, os.getenv("SMTP_HOST", "smtp.gmail.com"),
                                          int(os.getenv("SMTP_PORT", "587")),
                                          os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    else:
        resultat["envoye"] = False
    print(json.dumps(resultat, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
