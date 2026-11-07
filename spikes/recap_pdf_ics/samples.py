"""Deux recaps d'exemple.

- demo-nantes : reprend la maquette (tout est fictif).
- lisbonne-h  : missions hotel et transport alimentees par 2 vraies sessions H terminees
  (captures et chiffres lus via l'API H), inscription bloquee (semi complet).
"""

import json
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from models import (
    Capture, ChecklistItem, CourseProfile, ElevationPoint, FieldRow, HRun, HumanValidation,
    KeyFact, Mission, PaceRow, Recap, Runner, Source, TimelineItem,
)

HERE = Path(__file__).parent
PARIS = ZoneInfo("Europe/Paris")
LISBON = ZoneInfo("Europe/Lisbon")
CAMILLE = Runner(full_name="Camille Martin", email="camille.martin@example.com", birth_date=date(1994, 5, 12), goal="1 h 45")


def _p(y, mo, d, h, mi, tz=PARIS):
    return datetime(y, mo, d, h, mi, tzinfo=tz)


def _nantes_profile() -> CourseProfile:
    pts = []
    for i in range(0, 212):
        km = i / 10
        alt = 6 + 0.4 * km
        alt += 26 * math.exp(-((km - 6.2) ** 2) / 0.9)
        alt += 36 * math.exp(-((km - 15.0) ** 2) / 0.8)
        alt -= 5 * math.exp(-((km - 12.0) ** 2) / 2.0)
        alt += 1.2 * math.sin(km * 3.1)
        pts.append(ElevationPoint(km=round(min(km, 21.1), 2), alt_m=round(max(alt, 1), 1)))
    return CourseProfile(
        points=pts,
        aid_stations_km=[5, 10, 15, 20],
        climbs=[(14.0, 16.0, "Côte km 14-16 · +41 m")],
        annotations=[(9.8, "pont : altitude corrigée")],
        note="Altitude du pont corrigée (le modèle de terrain donnait celle du fleuve). D+ présenté comme estimation.",
    )


def demo_nantes() -> Recap:
    gen = _p(2026, 11, 7, 16, 42)
    return Recap(
        id="demo-nantes",
        is_mockup=True,
        mockup_notice="Maquette de démonstration. Course, coureur, prix, horaires et liens sont des données d'exemple inventées.",
        generated_at=gen,
        race_name="Semi des Bords de Loire 2027 (course d'exemple)",
        race_city="Nantes",
        race_date=date(2027, 4, 4),
        voice_request="Je veux courir le semi de Nantes en avril, objectif moins d'1h45.",
        runner=CAMILLE,
        key_facts=[
            KeyFact(label="Départ", value="Dim. 4 avril · 9:30", detail="Quai de la Fosse, sas fermés à 9:15", source=1),
            KeyFact(label="Retrait du dossard", value="Sam. 3 avril · 10:00–19:00", detail="Village course, parc des Chantiers", source=1),
            KeyFact(label="Documents exigés", value="PPS ou licence FFA + pièce d'identité", detail="PPS valable 3 mois", source=2),
            KeyFact(label="Parcours", value="21,1 km · D+ ≈ {dplus} m (estimé)", detail="1 côte notable au km 14", source=3),
            KeyFact(label="Ravitaillements", value="km 5, 10, 15, 20", detail="eau aux 4, fruits à partir du km 10", source=1),
            KeyFact(label="Temps limite", value="2 h 45", detail="consigne sacs sur le village", source=1),
        ],
        timeline=[
            TimelineItem(start=_p(2027, 4, 3, 8, 52), end=_p(2027, 4, 3, 11, 1), title="Train Paris-Montparnasse → Nantes", detail="arrivée 11:01", tag="a_payer", location="Gare Montparnasse, Paris"),
            TimelineItem(start=_p(2027, 4, 3, 11, 30), end=_p(2027, 4, 3, 12, 15), title="Retrait du dossard au village", detail="tram ligne 1, 12 min depuis la gare. Prends ton PPS et ta pièce d'identité.", tag="info", location="Parc des Chantiers, Nantes"),
            TimelineItem(start=_p(2027, 4, 3, 15, 0), end=_p(2027, 4, 3, 15, 30), title="Check-in hôtel", detail="650 m du départ, 8 min à pied", tag="a_payer", location="Hôtel Accor (exemple), Nantes"),
            TimelineItem(start=_p(2027, 4, 3, 19, 30), title="Dîner, puis préparation des affaires", detail="dossard, épingles, gel", tag="conseil", in_calendar=False),
            TimelineItem(start=_p(2027, 4, 4, 6, 45), title="Lever conseillé", detail="petit-déjeuner 2 h 30 avant le départ", tag="conseil", in_calendar=False),
            TimelineItem(start=_p(2027, 4, 4, 8, 40), title="Départ de l'hôtel à pied", detail="8 min, consigne du sac avant 9:00", tag="info", in_calendar=False),
            TimelineItem(start=_p(2027, 4, 4, 9, 30), end=_p(2027, 4, 4, 11, 15), title="Départ du semi", detail="arrivée visée vers 11:15", tag="inscription_prete", location="Quai de la Fosse, Nantes"),
            TimelineItem(start=_p(2027, 4, 4, 12, 0), title="Check-out tardif accordé jusqu'à 13:00", detail="douche après la course", tag="info", in_calendar=False),
            TimelineItem(start=_p(2027, 4, 4, 16, 58), end=_p(2027, 4, 4, 19, 5), title="Train Nantes → Paris-Montparnasse", detail="arrivée 19:05", tag="a_payer", location="Gare de Nantes"),
        ],
        missions=[
            Mission(
                key="inscription", title="Inscription au semi",
                fields=[
                    FieldRow(label="Plateforme", value="Njuko (page officielle trouvée par Linkup)"),
                    FieldRow(label="Épreuve", value="Semi-marathon 21,1 km, sas 1 h 40–1 h 50"),
                    FieldRow(label="Champs remplis", value="Nom, prénom, date de naissance, sexe, club : aucun, contact d'urgence, taille de t-shirt M"),
                ],
                price_eur=39.90, price_label="38,00 € + 1,90 € de frais de service",
                finalize_url="https://njuko.net/exemple/registration/summary", finalize_label="Finaliser et payer l'inscription",
                run=HRun(duration_s=372, steps=23),
                capture=Capture(caption="Capture H prise juste avant le paiement (maquette)", page_url="njuko.net/…/registration/summary", stop_button_label="Procéder au paiement"),
                validations=[HumanValidation(at=_p(2026, 11, 7, 16, 31) .replace(second=7), channel="voix", what="règlement de l'épreuve et consentement RGPD")],
                note="La case PPS a été laissée à cocher par toi au moment du paiement.",
            ),
            Mission(
                key="hotel", title="Hôtel",
                fields=[
                    FieldRow(label="Site", value="all.accor.com"),
                    FieldRow(label="Hôtel", value="Hôtel 3★ du groupe Accor (exemple), 650 m de la ligne de départ"),
                    FieldRow(label="Pourquoi celui-là", value="Critère dicté en cours de route : « à moins de 10 min à pied du départ ». 4 hôtels comparés."),
                    FieldRow(label="Séjour", value="Sam. 3 → dim. 4 avril · 1 nuit · 1 adulte · annulation gratuite jusqu'au 2 avril"),
                ],
                price_eur=96.00, price_label="96,00 € petit-déjeuner inclus (servi dès 6:30)",
                finalize_url="https://all.accor.com/exemple/booking/guest-details", finalize_label="Finaliser et payer l'hôtel",
                run=HRun(duration_s=588, steps=31),
                capture=Capture(caption="Capture H prise juste avant le paiement (maquette)", page_url="all.accor.com/…/booking/guest-details", stop_button_label="Continuer vers le paiement"),
            ),
            Mission(
                key="transport", title="Transport",
                fields=[
                    FieldRow(label="Site", value="Site de transport retenu par la boucle de tests (exemple)"),
                    FieldRow(label="Aller", value="Sam. 3 avril · 08:52 → 11:01 · direct"),
                    FieldRow(label="Retour", value="Dim. 4 avril · 16:58 → 19:05 · direct"),
                    FieldRow(label="Pourquoi ces horaires", value="Arrivée avant l'ouverture large du retrait, retour après check-out et 5 h de marge après l'arrivée visée"),
                ],
                price_eur=78.00, price_label="78,00 € aller-retour, 2e classe",
                finalize_url="https://transport.example/basket", finalize_label="Finaliser et payer le train",
                run=HRun(duration_s=450, steps=27),
                capture=Capture(caption="Capture H prise juste avant le paiement (maquette)", page_url="…/basket", stop_button_label="Payer"),
            ),
        ],
        profile=_nantes_profile(),
        pace_plan=[
            PaceRow(km="0–3", profile="plat, foule", pace="5'05\"", advice="ne pas partir trop vite"),
            PaceRow(km="3–9", profile="roulant", pace="4'56\"", advice="trouver ton rythme"),
            PaceRow(km="9–14", profile="pont puis plat", pace="4'57\"", advice="gel au ravito km 10"),
            PaceRow(km="14–16", profile="côte +41 m", pace="5'15\"", advice="garder l'effort, pas l'allure"),
            PaceRow(km="16–21,1", profile="descente puis plat", pace="4'52\"", advice="relancer, finir fort"),
        ],
        pace_note="Temps de passage : 10 km en 49'45\", 15 km en 1 h 15'05\".",
        morning=[
            FieldRow(label="Hôtel → départ", value="650 m, 8 min à pied (tracé sur la carte du survol)"),
            FieldRow(label="Consigne", value="ouverte 7:30–9:00, village course"),
            FieldRow(label="Fermeture des sas", value="9:15"),
            FieldRow(label="Météo moyenne début avril", value="8 °C à 9 h, 14 °C à midi (moyenne historique, pas une prévision)"),
            FieldRow(label="Résultats 2026", value="temps médian du semi : 2 h 02 · un chrono de 1 h 45 classe dans les ~25 % premiers"),
        ],
        flyover_url="https://runai.example/survol/demo-nantes",
        checklist=[
            ChecklistItem(text="Payer l'inscription (lien mission 1)"),
            ChecklistItem(text="Payer l'hôtel (lien mission 2), avant le 2 avril pour garder le tarif"),
            ChecklistItem(text="Payer le train (lien mission 3)"),
            ChecklistItem(text="Faire le PPS en ligne (valable 3 mois, à présenter au retrait)"),
            ChecklistItem(text="Règlement de l'épreuve lu et validé", done=True),
            ChecklistItem(text="Pièce d'identité dans le sac"),
            ChecklistItem(text="Épingles, gels, tenue adaptée à 8 °C"),
            ChecklistItem(text="Ajouter week-end.ics à ton agenda"),
        ],
        sources=[
            Source(label="Règlement officiel 2027 (PDF), site de l'organisateur", found_by="Linkup", used_for="départ, retrait, ravitos, temps limite"),
            Source(label="Page « PPS » de la FFA", found_by="Linkup", used_for="documents exigés"),
            Source(label="Tracé GPX exporté depuis la page parcours", found_by="agent H éclaireur", used_for="profil, côtes, allures"),
            Source(label="Pages de paiement Njuko, Accor et transport", found_by="agents H", used_for="prix, captures, liens de paiement"),
        ],
    )


def _h(name: str) -> dict:
    return json.loads((HERE / "assets" / f"{name}.json").read_text())


def lisbonne_h() -> Recap:
    accor, tap = _h("h_accor_guest_details"), _h("h_tap_passengers")
    return Recap(
        id="lisbonne-h",
        is_mockup=False,
        mockup_notice=(
            "Coureur fictif. Hôtel et vol : vraies sessions H du 7 nov. 2026 (arrêt avant paiement, rien n'a été payé). "
            "Inscription non lancée : le semi 2027 est complet."
        ),
        generated_at=datetime.now(PARIS).replace(microsecond=0),
        race_name="EDP Meia Maratona de Lisboa 2027",
        race_city="Lisbonne",
        race_date=date(2027, 3, 7),
        voice_request="Je veux courir le semi de Lisbonne en mars.",
        runner=CAMILLE,
        key_facts=[
            KeyFact(label="Départ", value="Dim. 7 mars 2027 · 9:30 (heure de Lisbonne)", detail="règlement 2027", source=1),
            KeyFact(label="Inscriptions", value="Complet", detail="la page bascule sur une liste d'attente", source=2),
            KeyFact(label="Retrait du dossard", value="Non trouvé", detail="à compléter par Linkup", source=None),
        ],
        timeline=[
            TimelineItem(start=_p(2027, 3, 6, 6, 40), end=datetime(2027, 3, 6, 8, 15, tzinfo=LISBON), title="Vol TAP TP 0441 Orly → Lisbonne", detail="direct, 2 h 35, arrivée 08:15 heure de Lisbonne", tag="a_payer", location="Paris-Orly (ORY)"),
            TimelineItem(start=datetime(2027, 3, 6, 14, 0, tzinfo=LISBON), end=datetime(2027, 3, 6, 14, 30, tzinfo=LISBON), title="Check-in ibis Lisboa Centro Liberdade", detail="arrivée à partir de 14:00", tag="a_payer", location="ibis Lisboa Centro Liberdade, Lisbonne"),
            TimelineItem(start=datetime(2027, 3, 7, 9, 30, tzinfo=LISBON), end=datetime(2027, 3, 7, 11, 30, tzinfo=LISBON), title="Départ du semi (inscription complète)", detail="liste d'attente uniquement", tag="info", location="Lisbonne"),
            TimelineItem(start=datetime(2027, 3, 8, 12, 0, tzinfo=LISBON), end=datetime(2027, 3, 8, 12, 15, tzinfo=LISBON), title="Check-out hôtel", detail="départ avant 12:00", tag="info", location="ibis Lisboa Centro Liberdade, Lisbonne"),
        ],
        missions=[
            Mission(
                key="inscription", title="Inscription au semi", status="bloque",
                fields=[
                    FieldRow(label="Plateforme", value="meia-maratona.inscricoes.maratonaportugal.com"),
                    FieldRow(label="État", value="semi 2027 complet, liste d'attente"),
                ],
                note="Agent non lancé : aucune page de paiement à préparer. RunAI propose une autre course.",
            ),
            Mission(
                key="hotel", title="Hôtel",
                fields=[
                    FieldRow(label="Site", value="all.accor.com (mode invité)"),
                    FieldRow(label="Hôtel", value="ibis Lisboa Centro Liberdade"),
                    FieldRow(label="Séjour", value="6 → 8 mars 2027 · 2 nuits · 1 adulte · Quarto Standard"),
                    FieldRow(label="Champs remplis", value="aucun (test sans données personnelles)"),
                ],
                price_eur=185.41, price_label="185,41 € taxes incluses (tarif le moins cher)",
                finalize_url=accor["page_url"], finalize_label="Finaliser et payer l'hôtel",
                run=HRun(session_id=accor["session_id"], duration_s=accor["duration_s"], steps=accor["steps"], agent_view_url=accor["agent_view_url"], measured=True),
                capture=Capture(image_path="assets/h_accor_guest_details.png", page_url=accor["page_url"], taken_at=accor["capture_at"], caption="Vraie capture H, dernière observation avant paiement", real=True),
                note="Durée API totale du run : 1374 s, dont une attente volontaire sur la page (test de maintien du panier).",
            ),
            Mission(
                key="transport", title="Transport",
                fields=[
                    FieldRow(label="Site", value="flytap.com (mode invité)"),
                    FieldRow(label="Aller", value="Sam. 6 mars 2027 · TP 0441 · 06:40 Orly → 08:15 Lisbonne · direct"),
                    FieldRow(label="Retour", value="non demandé dans ce test"),
                    FieldRow(label="Champs remplis", value="aucun (test sans données personnelles)"),
                ],
                price_eur=103.47, price_label="103,47 € aller simple, tarif Discount",
                finalize_url=tap["page_url"], finalize_label="Finaliser et payer le vol",
                run=HRun(session_id=tap["session_id"], duration_s=tap["duration_s"], steps=tap["steps"], agent_view_url=tap["agent_view_url"], measured=True),
                capture=Capture(image_path="assets/h_tap_passengers.png", page_url=tap["page_url"], taken_at=tap["capture_at"], caption="Vraie capture H, dernière observation avant paiement", real=True),
                note="Durée API totale du run : 1356 s, dont une attente volontaire sur la page (test de maintien du panier).",
            ),
        ],
        checklist=[
            ChecklistItem(text="Choisir une autre course ou s'inscrire en liste d'attente"),
            ChecklistItem(text="Payer l'hôtel (lien mission 2)"),
            ChecklistItem(text="Payer le vol (lien mission 3)"),
            ChecklistItem(text="Ajouter week-end.ics à ton agenda"),
        ],
        sources=[
            Source(label="Règlement EDP Meia Maratona de Lisboa 2027", found_by="recherche RunAI", used_for="heure de départ"),
            Source(label="Page d'inscription Maratona Clube de Portugal", found_by="recherche RunAI", used_for="statut complet"),
            Source(label=f"Session H {accor['session_id']} (all.accor.com)", found_by="agent H", used_for="prix, capture, lien hôtel", url=accor["agent_view_url"]),
            Source(label=f"Session H {tap['session_id']} (flytap.com)", found_by="agent H", used_for="prix, capture, lien vol", url=tap["agent_view_url"]),
        ],
    )


RECAPS = {"demo-nantes": demo_nantes, "lisbonne-h": lisbonne_h}


def get_recap(recap_id: str) -> Recap | None:
    factory = RECAPS.get(recap_id)
    return factory() if factory else None
