"""Récap d'exemple : Wizz Air Milano Marathon 2027, profil et réservations fictifs."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from runai.models import (
    Race,
    RunnerProfile,
    Source,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
)

from .build import default_timeline, recap_from_mission
from .models import KeyFact, Recap, RecapSource, TimelineItem

MILAN = ZoneInfo("Europe/Rome")
NJUKO_URL = "https://in.njuko.com/wizz-air-milano-marathon-20271776152378557"


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2027, 4, day, hour, minute, tzinfo=MILAN)


DEMO_RACE = Race(
    name="Wizz Air Milano Marathon 2027",
    city="Milan",
    country="IT",
    race_date=date(2027, 4, 4),
    start_time="08:00",
    distance_km=42.195,
    registration_url=NJUKO_URL,
    bib_pickup="Village marathon, sam. 3 avril (horaires d'exemple)",
    start_location="Corso Venezia (exemple)",
    sources=[Source(url=NJUKO_URL, title="Page d'inscription Njuko")],
)

DEMO_STEPS = [
    StepResult(kind=StepKind.search, status=StepStatus.completed, summary="Course trouvée par Linkup."),
    StepResult(
        kind=StepKind.registration, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.health_declaration, url=NJUKO_URL, price_eur=114.0,
        summary="Formulaire Njuko pré-rempli avec le profil fictif, arrêt à l'étape licence / certificat médical.",
        h_session_id="demo-registration",
    ),
    StepResult(
        kind=StepKind.accommodation, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.payment, url="https://example.org/hotel-milano/paiement", price_eur=238.0,
        summary="Hôtel d'exemple à 900 m du départ, 2 nuits (3 au 5 avril), 1 adulte.",
        h_session_id="demo-accommodation",
    ),
    StepResult(
        kind=StepKind.transport, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.payment, url="https://example.org/train-paris-milano/paiement", price_eur=139.8,
        summary="Train direct Paris Gare de Lyon ⇄ Milano Centrale, aller sam. 3 avril, retour lun. 5 avril.",
        h_session_id="demo-transport",
    ),
]


def _timeline() -> list[TimelineItem]:
    race_items = [t for t in default_timeline(DEMO_RACE) if t.tag == "course"]
    return race_items + [
        TimelineItem(start=_t(3, 6, 28), end=_t(3, 13, 35), title="Train Paris Gare de Lyon → Milano Centrale",
                     detail="direct, arrivée 13:35", location="Gare de Lyon, Paris", tag="a_payer"),
        TimelineItem(start=_t(3, 15, 0), end=_t(3, 15, 30), title="Check-in hôtel",
                     detail="900 m du départ", location="Hôtel d'exemple, Milan", tag="a_payer"),
        TimelineItem(start=_t(3, 16, 0), end=_t(3, 17, 0), title="Retrait du dossard au village",
                     detail="pièce d'identité + documents médicaux", location="Village marathon (exemple)",
                     tag="info", alarm_minutes=120),
        TimelineItem(start=_t(3, 19, 30), title="Dîner, préparation des affaires", detail="dossard, épingles, gels",
                     tag="conseil", in_calendar=False),
        TimelineItem(start=_t(4, 5, 15), title="Lever conseillé", detail="petit-déjeuner 2 h 30 avant le départ",
                     tag="conseil", in_calendar=False),
        TimelineItem(start=_t(5, 9, 10), end=_t(5, 16, 20), title="Train Milano Centrale → Paris Gare de Lyon",
                     detail="direct, arrivée 16:20", location="Milano Centrale", tag="a_payer"),
    ]


def demo_recap() -> Recap:
    return recap_from_mission(
        DEMO_RACE,
        RunnerProfile(),
        DEMO_STEPS,
        recap_id="demo-milan",
        voice_request="Je veux courir le marathon de Milan en avril, je pars de Paris, objectif 3 h 45.",
        goal="3 h 45",
        options={
            StepKind.registration: ["Catégorie compétitive (licence FFA ou RUNCARD)"],
            StepKind.accommodation: ["Petit-déjeuner inclus", "Annulation gratuite jusqu'au 1er avril"],
            StepKind.transport: ["2e classe, places assises côte fenêtre", "Billets échangeables"],
        },
        timeline=_timeline(),
        key_facts=[
            KeyFact(label="Départ", value="Dim. 4 avril 2027 · 08:00", detail="Corso Venezia (exemple)", source=1),
            KeyFact(label="Distance", value="42,195 km", detail="marathon, parcours urbain", source=1),
            KeyFact(label="Inscription", value="114 € sur Njuko", detail="tarif valable jusqu'au 31 déc. 2026, lu le 7 nov. 2026", source=1),
            KeyFact(label="Statut compétitif", value="Licence World Athletics (FFA) ou RUNCARD",
                    detail="sinon catégorie non compétitive ; certificat médical italien pour la RUNCARD (règles 2026)",
                    source=2),
            KeyFact(label="Retrait du dossard", value="Sam. 3 avril", detail="village marathon (exemple)", source=1),
            KeyFact(label="Objectif", value="3 h 45", detail="allure moyenne 5:20 /km"),
        ],
        checklist=[
            "Joindre ta licence FFA, ou obtenir la RUNCARD et le certificat médical italien, ou choisir la catégorie non compétitive.",
            "Emporter une pièce d'identité pour le retrait du dossard.",
            "Importer week-end.ics dans ton agenda.",
        ],
        extra_sources=[RecapSource(label="Site officiel Milano Marathon (règlement 2026)", url="https://www.milanomarathon.it/",
                                   found_by="Linkup", used_for="règles pour les coureurs étrangers")],
        notice="Exemple de démonstration : profil coureur, hôtel, trains, horaires et liens d'agents sont fictifs. "
               "Rien n'a été payé ni soumis.",
        generated_at=datetime(2026, 11, 7, 15, 42, tzinfo=UTC),
    )
