import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import agenda_ics
import mail_inbound
import mail_recap
import niveau
import pytest
import strava_client

FIX = Path(__file__).parent.parent / "fixtures"
RECAP = json.loads((FIX / "recap_weekend.json").read_text(encoding="utf-8"))


def _agenda():
    fin = datetime(2027, 5, 31, 23, 59, tzinfo=agenda_ics.TZ_DEFAUT)
    return agenda_ics.lire_ics((FIX / "agenda_camille.ics").read_text(encoding="utf-8"), fin)


def test_agenda_week_ends():
    ag = _agenda()
    wk = {w["samedi"]: w for w in agenda_ics.week_ends(ag, date(2026, 11, 9), date(2027, 5, 31))}
    assert not wk["2026-11-14"]["libre"]  # yoga, semaine 1
    assert wk["2026-11-21"]["libre"]  # yoga une semaine sur deux
    assert not wk["2026-12-05"]["libre"]  # mariage
    assert not wk["2026-12-26"]["libre"]  # vacances
    assert not wk["2027-01-16"]["libre"]  # déjeuner dimanche
    assert not wk["2027-02-13"]["libre"] and not wk["2027-02-20"]["libre"]  # ski
    assert wk["2027-03-06"]["libre"] is False and wk["2027-03-06"]["vendredi_soir_libre"] is False  # séminaire
    assert wk["2027-03-20"]["libre"]  # événement transparent
    assert wk["2027-04-03"]["libre"]  # événement annulé
    assert not wk["2027-01-23"]["libre"] and wk["2027-02-06"]["libre"]  # yoga UNTIL 30/01
    assert any("MONTHLY" in w for w in ag.warnings)


def test_filtrer_courses():
    ag = _agenda()
    wk = agenda_ics.week_ends(ag, date(2026, 11, 9), date(2027, 5, 31))
    courses = json.loads((FIX / "courses_candidates.json").read_text(encoding="utf-8"))
    res = {c["nom"]: c for c in agenda_ics.filtrer_courses(courses, wk, date(2026, 11, 9), "debutant")}
    assert res["Wizz Air Milano Marathon"]["statut"] == "compatible"
    assert res["10 km fictif de Noël"]["statut"] == "conflit_agenda"
    assert res["Vodafone 10K (Lisbonne)"]["statut"] == "conflit_agenda"
    assert res["Semi fictif d'hiver"]["statut"] == "trop_tot"
    assert res["Trail fictif des Crêtes"]["statut"] == "trop_tot"  # 25 km + 1200 m D+, débutant : 24 sem.


def test_ics_export_relu():
    ics = agenda_ics.construire_ics(agenda_ics.evenements_week_end(RECAP))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert all(len(lg.encode()) <= 75 for lg in ics.split("\r\n"))
    relu = agenda_ics.lire_ics(ics)
    assert len(relu.occupations) == 5
    course = next(o for o in relu.occupations if o.titre.startswith("Course"))
    assert course.debut == datetime(2027, 4, 4, 6, 30, tzinfo=UTC)


def test_mail_eml_valide(tmp_path):
    msg = mail_recap.construire_message(RECAP, "RunAI <runai@example.com>", "camille.martin@example.com",
                                        "runai+sess123@abc.resend.app")
    brut = msg.as_bytes()
    v = mail_recap.valider_eml(brut)
    assert v["ok"], v["erreurs"]
    assert v["pieces_jointes"] == ["recap.pdf", "weekend.ics"] and v["nb_vevent"] == 5
    r = mail_recap.payload_resend(msg)
    assert r["reply_to"] == "runai+sess123@abc.resend.app" and len(r["attachments"]) == 2
    assert base64.b64decode(r["attachments"][0]["content"]).startswith(b"%PDF-")
    assert mail_recap.payload_brevo(msg)["attachment"][1]["name"] == "weekend.ics"


def _signe(secret_brut: bytes, corps: bytes, ts: int) -> dict:
    sig = base64.b64encode(hmac.new(secret_brut, f"msg_1.{ts}.".encode() + corps, hashlib.sha256).digest()).decode()
    return {"svix-id": "msg_1", "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}"}


def test_inbound_vers_h():
    secret_brut = b"0123456789abcdef0123456789abcdef"
    secret = "whsec_" + base64.b64encode(secret_brut).decode()
    corps = json.dumps({"type": "email.received", "data": {
        "email_id": "em_1", "to": ["runai+sess123@abc.resend.app"], "from": "camille.martin@example.com"}}).encode()
    envoyes = []
    lire = lambda i: {"text": "Prends plutôt la chambre avec petit-déjeuner.\n\nLe sam. 7 nov., RunAI a écrit :\n> récap"}
    res = mail_inbound.traiter(corps, _signe(secret_brut, corps, int(time.time())), secret, lire,
                               lambda s, t: envoyes.append((s, t)))
    assert res["session_id"] == "sess123"
    assert envoyes == [("sess123", "Prends plutôt la chambre avec petit-déjeuner.")]
    with pytest.raises(mail_inbound.SignatureInvalide):
        mail_inbound.traiter(corps + b" ", _signe(secret_brut, corps, int(time.time())), secret, lire, print)
    with pytest.raises(mail_inbound.SignatureInvalide):
        mail_inbound.traiter(corps, _signe(secret_brut, corps, int(time.time()) - 3600), secret, lire, print)
    autre = mail_inbound.traiter(corps, _signe(secret_brut, corps, int(time.time())), secret, lire, print, {"x"})
    assert autre == {"ignore": "session inconnue"}


def test_strava_fixture_vers_estimateur():
    resumes, details = strava_client.lire_fixture()
    p = strava_client.profil_coureur(resumes, details, 90, datetime(2026, 11, 7, tzinfo=UTC), "fixture")
    assert p["nb_sorties"] == 36 and p["activites_detaillees"] == 20
    noms = [e["nom"] for e in p["meilleurs_efforts"]]
    assert "400m" not in noms and "5K" in noms and "10K" in noms
    est = niveau.estimer(p)
    assert est["niveau"] in {"debutant", "intermediaire", "confirme"}
    assert "Marathon" not in est["distances_conseillees"]


def test_niveau_sans_chrono():
    est = niveau.estimer({"sorties_par_semaine": 1, "plus_longue_sortie_km": 5})
    assert est["niveau"] == "debutant" and est["hypotheses"]
    assert niveau.riegel(3000, 10000, 21097.5) == pytest.approx(6631, rel=0.01)
