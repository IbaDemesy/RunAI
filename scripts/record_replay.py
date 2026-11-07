"""Record an offline demo; live recordings use the replay export endpoint."""

import argparse
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from runai.app.providers import DEFAULT_REPLAY_TRACE
from runai.app.replay import ReplayTrace
from runai.app.server import build_demo_service, create_app

DEMO_TRANSLATIONS = {
    "Formulaire pré-rempli ; arrêt avant la case « J'accepte le règlement »":
        "Form prefilled; stopped before accepting the rules",
    "Chambre sélectionnée pour la veille de la course ; arrêt avant le paiement":
        "Room selected for the night before the race; stopped before payment",
    "Aller-retour sélectionné ; arrêt avant le paiement":
        "Round trip selected; stopped before payment",
    "Prêt : à finaliser vous-même sur le site officiel":
        "Ready: finalize yourself on the official website",
    "Quel sas souhaitez-vous examiner (démo) ?": "Which starting group should we review (demo)?",
    "Quel temps visez-vous ? (pour le sas de départ)": "What is your target finishing time?",
    "Préférence horaire pour le trajet confirmé (démo) ?": "Preferred departure time (demo)?",
    "Ouverture de la page d'inscription": "Opening the registration page",
    "Choix de la distance": "Choosing the distance",
    "Saisie du nom et du prénom (profil fictif)": "Entering a fictional runner name",
    "Saisie de l'e-mail et de la date de naissance": "Entering email and birth date",
    "Page « Règlement et certificat médical » atteinte": "Rules and medical certificate page reached",
    "Recherche d'hôtels près du départ": "Searching for hotels near the start",
    "Filtre : annulation gratuite": "Filtering for free cancellation",
    "Sélection de l'hôtel le plus proche du départ": "Selecting the hotel nearest the start",
    "Saisie des coordonnées du voyageur (profil fictif)": "Entering fictional traveler details",
    "Recherche d'un aller-retour": "Searching for a round trip",
    "Choix de l'aller la veille de la course": "Selecting outbound travel the day before the race",
    "Choix du retour après l'arrivée": "Selecting return travel after finishing",
    "Saisie du passager (profil fictif)": "Entering a fictional passenger",
    "Page de paiement atteinte": "Payment page reached",
    "Réponses utilisateur": "User answers",
    "Source factice": "Fictional source",
    "agent lancé": "agent started",
    "Inscription": "Registration",
    "Hébergement": "Accommodation",
    "Découverte": "Discovery",
    "moins de 3h30": "under 3h30",
    "plus de 4h": "over 4h",
    "après-midi": "afternoon",
    "matin": "morning",
    "nuits": "nights",
    "Démo": "Demo",
    "démo": "demo",
}


def english_demo(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: english_demo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [english_demo(item) for item in value]
    if isinstance(value, str):
        for original, translated in DEMO_TRANSLATIONS.items():
            value = value.replace(original, translated)
    return value


def confirm_marathon(client: TestClient) -> str:
    response = client.post("/api/framings", json={
        "text": "a marathon in Milan, 42.195 km on 2027-04-11, from Lyon, 900 euros, 2 nights, train",
    })
    response.raise_for_status()
    session = response.json()
    response = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
    })
    response.raise_for_status()
    session = response.json()
    response = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "corrections": {
            "origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "train",
        },
    })
    response.raise_for_status()
    session = response.json()
    response = client.post(f"/api/framings/{session['id']}/confirm", json={
        "revision": session["revision"], "idempotency_key": "record-demo-replay",
    })
    response.raise_for_status()
    return response.json()["mission_id"]


def finish_mission(client: TestClient, mission_id: str) -> dict:
    for _ in range(2000):
        response = client.get(f"/api/missions/{mission_id}")
        response.raise_for_status()
        mission = response.json()
        for question in mission["questions"]:
            if question["status"] == "open":
                response = client.post(
                    f"/api/missions/{mission_id}/questions/{question['question_id']}/answer",
                    json={
                        "revision": question["revision"],
                        "idempotency_key": f"record-{question['question_id']}",
                        "answer": question["choices"][0],
                    },
                )
                response.raise_for_status()
        if mission["status"] in {"awaiting_human", "completed", "failed", "cancelled"}:
            return mission
        time.sleep(.005)
    raise TimeoutError("Demo mission did not finish")


def record_demo(path: Path) -> None:
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mission_id = confirm_marathon(client)
        mission = finish_mission(client, mission_id)
        if mission["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"Demo mission ended as {mission['status']}")
        response = client.get(f"/api/missions/{mission_id}/replay.json")
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        ReplayTrace.model_validate(english_demo(response.json())).dump(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPLAY_TRACE)
    args = parser.parse_args()
    record_demo(args.output)
    print(f"Recorded demo replay: {args.output}")


if __name__ == "__main__":
    main()
