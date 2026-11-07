"""Spike axe 4 : transport via un agent H (h/web-surfer-pro), arret avant paiement.

Usage : python spikes/transport_h/run_transport.py <cible>   (cibles : voir TARGETS)
Ecrit spikes/transport_h/results/<cible>_<horodatage>.json (reponse, statut, duree, evenements).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from hai_agents import Client
from pydantic import BaseModel, Field

RESULTS = Path(__file__).parent / "results"
AGENT = "h/web-surfer-pro"
MAX_STEPS = 80
MAX_TIME_S = 1200

PASSENGER = (
    "Passager fictif (donnees de test, ne jamais en saisir d'autres) : Madame Camille Martin, "
    "nee le 12/05/1994, nationalite francaise, e-mail camille.martin@example.com, "
    "telephone +33 6 12 34 56 78. Aucun bagage en soute, aucune option payante."
)

SAFETY = (
    "REGLES ABSOLUES : ne paie jamais, ne saisis aucune carte bancaire, ne clique jamais sur un bouton "
    "qui finalise la commande (Payer, Confirmer et payer, Reserver definitivement). Ne cree aucun compte et "
    "ne te connecte a aucun compte : si le site exige un compte, une connexion ou un vrai e-mail verifie, "
    "arrete-toi et note-le dans blocages. Refuse les cookies non essentiels si possible. Si un captcha "
    "apparait, ne le contourne pas : note-le (captcha_rencontre=true) et arrete-toi. Arrete-toi sur la "
    "derniere page avant paiement (page de recapitulatif / choix du moyen de paiement) et decris-la."
)

TARGETS = {
    "trainline": {
        "start_url": "https://www.thetrainline.com/fr",
        "task": (
            "Contexte : un coureur va au Wizz Air Milano Marathon le dimanche 4 avril 2027 (depart vers 9h). "
            "Le retrait des dossards se fait au village du marathon a Milan le samedi 3 avril 2027 (avant 19h). "
            "Sur Trainline (https://www.thetrainline.com/fr), cherche un aller simple en train Paris -> Milano "
            "(Milano Centrale ou Porta Garibaldi) le samedi 3 avril 2027, 1 adulte, 2e classe / Standard, "
            "en choisissant un train direct du matin qui arrive a Milan avant 16h pour laisser le temps de "
            "retirer le dossard. Si aucun train n'est encore en vente a cette date, note-le dans blocages "
            "puis refais la meme recherche le samedi le plus proche ou des trains Paris -> Milano sont en vente, "
            "pour mesurer le parcours jusqu'au paiement. Choisis le tarif le moins cher, remplis le passager "
            "et va jusqu'a la page juste avant paiement."
        ),
    },
    "tap": {
        "start_url": "https://www.flytap.com/fr-fr",
        "task": (
            "Contexte : un coureur va a la Vodafone 10K de Lisbonne le dimanche 7 mars 2027 (depart le matin). "
            "Le retrait des dossards a lieu le samedi 6 mars 2027 a Lisbonne. Sur le site de TAP Air Portugal "
            "(https://www.flytap.com/fr-fr), cherche un aller-retour Paris (Orly ou CDG) -> Lisbonne, 1 adulte, "
            "classe economique : aller le samedi 6 mars 2027 avec un vol du matin qui arrive avant 14h, "
            "retour le dimanche 7 mars 2027 avec un vol qui part apres 16h. Choisis le tarif le moins cher "
            "(Discount / Classic), continue en invite, remplis le passager et va jusqu'a la page juste avant paiement."
        ),
    },
    "kombo": {
        "start_url": "https://www.kombo.co/fr",
        "task": (
            "Contexte : un coureur va au Wizz Air Milano Marathon le dimanche 4 avril 2027 (depart vers 9h). "
            "Le retrait des dossards se fait au village du marathon a Milan le samedi 3 avril 2027 (avant 19h). "
            "Sur Kombo (https://www.kombo.co/fr), cherche un aller simple en train Paris -> Milan le samedi "
            "3 avril 2027, 1 adulte (passager de 32 ans, sans carte de reduction), avec un train direct du matin "
            "qui arrive a Milan avant 16h. Si rien n'est encore en vente a cette date, note-le dans blocages puis "
            "refais la meme recherche le samedi le plus proche ou des trains Paris -> Milan sont en vente, pour "
            "mesurer le parcours jusqu'au paiement. Choisis le tarif le moins cher, remplis le passager et va "
            "jusqu'a la page juste avant paiement."
        ),
    },
    "omio": {
        "start_url": "https://www.omio.fr",
        "task": (
            "Contexte : un coureur va au Wizz Air Milano Marathon le dimanche 4 avril 2027. Le retrait des "
            "dossards se fait le samedi 3 avril 2027 a Milan. Sur Omio (https://www.omio.fr), cherche un aller "
            "simple en train Paris -> Milan le samedi 3 avril 2027, 1 adulte, arrivee avant 16h. Si rien n'est "
            "en vente a cette date, note-le et refais la recherche le samedi le plus proche ou des trains sont en "
            "vente. Choisis le moins cher, remplis le passager et va jusqu'a la page juste avant paiement."
        ),
    },
}


class Trajet(BaseModel):
    sens: str = Field(description="aller ou retour")
    depart_gare_ou_aeroport: str
    arrivee_gare_ou_aeroport: str
    date: str = Field(description="AAAA-MM-JJ")
    heure_depart: str
    heure_arrivee: str
    operateur_ou_numero: str = Field(description="ex. TP433, Frecciarossa 9241, TGV INOUI 9241")
    correspondances: int
    tarif: str = Field(description="nom du tarif choisi")


class TransportAnswer(BaseModel):
    site: str
    trajets: list[Trajet]
    prix_total: float | None = Field(default=None, description="prix total affiche avant paiement")
    devise: str | None = None
    passager_rempli: bool = Field(description="le formulaire passager a ete rempli avec les donnees fictives")
    page_finale: str = Field(description="titre ou description de la derniere page atteinte")
    url_finale: str
    arret_avant_paiement: bool = Field(description="la derniere page est bien juste avant le paiement")
    captcha_rencontre: bool
    compte_exige: bool
    blocages: list[str] = Field(description="tout ce qui a bloque ou force un detour, avec l'etape")
    horaires_coherents_avec_course: str = Field(
        description="explique pourquoi les horaires collent au retrait du dossard (samedi) et a la course (dimanche)"
    )


def wait_for_slot(client: Client, max_wait_s: int = 600, every_s: int = 60) -> dict:
    t0 = time.monotonic()
    checks = []
    while True:
        q = client.sessions.get_session_quota()
        checks.append({"t": round(time.monotonic() - t0), "active": q.active, "available": q.available})
        print(f"quota: limit={q.limit} active={q.active} available={q.available}", flush=True)
        if q.available and q.available > 0:
            return {"waited_s": round(time.monotonic() - t0), "checks": checks}
        if time.monotonic() - t0 >= max_wait_s:
            raise SystemExit(f"Aucun slot H libre apres {max_wait_s} s : {checks}")
        time.sleep(every_s)


def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def main(target: str) -> None:
    load_dotenv()
    cfg = TARGETS[target]
    client = Client()
    quota = wait_for_slot(client)
    message = f"{cfg['task']}\n\n{PASSENGER}\n\n{SAFETY}\n\nPage de depart : {cfg['start_url']}"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{target}_{stamp}.json"
    RESULTS.mkdir(exist_ok=True)
    record: dict = {"target": target, "agent": AGENT, "quota_wait": quota, "prompt": message}
    t0 = time.monotonic()
    handle = client.start_session(
        agent=AGENT,
        messages=message,
        answer_schema=TransportAnswer,
        max_steps=MAX_STEPS,
        max_time_s=MAX_TIME_S,
        timezone="Europe/Paris",
    )
    record["session_id"] = handle.id
    print(f"session {handle.id}", flush=True)
    try:
        try:
            share = client.sessions.share_session(handle.id)
            record["share"] = dump(share)
        except Exception as e:  # noqa: BLE001  (partage optionnel)
            record["share_error"] = repr(e)
        result = handle.wait_for_completion(timeout_seconds=MAX_TIME_S + 120)
        record["wall_s"] = round(time.monotonic() - t0, 1)
        record["status"] = str(result.status)
        record["outcome"] = result.outcome
        record["error"] = result.error
        record["answer"] = dump(result.answer)
        record["events"] = [dump(e) for e in result.events]
        sess = handle.get()
        record["session"] = {
            "agent_view_url": sess.agent_view_url,
            "created_at": str(sess.created_at),
            "started_at": str(sess.started_at),
            "finished_at": str(sess.finished_at),
            "status": dump(sess.status),
        }
    except BaseException as e:
        record["wall_s"] = round(time.monotonic() - t0, 1)
        record["exception"] = repr(e)
        raise
    finally:
        try:
            handle.cancel()
            record["cancelled"] = True
        except Exception as e:  # noqa: BLE001
            record["cancel_error"] = repr(e)
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str))
        print(f"ecrit {out}", flush=True)
        print(json.dumps({k: record.get(k) for k in ("session_id", "wall_s", "status", "outcome", "error")}, default=str))
        print(json.dumps(record.get("answer"), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "trainline")
