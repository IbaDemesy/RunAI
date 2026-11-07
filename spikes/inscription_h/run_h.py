"""Spike axe 2 : un run H d'inscription (Njuko ou Klikego) arrêté avant paiement.

Usage : python spikes/inscription_h/run_h.py <cible>   (cibles dans CIBLES)
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from hai_agents import Client
from hai_agents.polling import AnswerValidationError, wait_for_session
from pydantic import BaseModel, Field

ICI = Path(__file__).parent
SKILLS = ICI / "skills"
RESULTATS = ICI / "resultats"

CIBLES = {
    "njuko_hyeres_10k": {
        "plateforme": "njuko",
        "course": "Semi Marathon de Hyères 2027",
        "epreuve": "10 KM DE HYERES LES PALMIERS (21/03/2027)",
        "url": "https://in.njuko.com/semi-marathon-de-hyeres-2027?currentPage=select-competition",
    },
    "klikego_boucle_seine_semi": {
        "plateforme": "klikego",
        "course": "Semi Marathon Boucle de Seine 2027 (Chatou)",
        "epreuve": "Semi-Marathon en individuel 21,1 km (21/03/2027)",
        "url": "https://www.klikego.com/inscription/semi-marathon-boucle-de-seine-2027/course-a-pied-running/1790283994662-1",
    },
    "njuko_cadourques_15k": {
        "plateforme": "njuko",
        "course": "Grand Trail des Cadourques 2027 (Cahors)",
        "epreuve": "Valentré (15 km) (03/04/2027)",
        "url": "https://in.njuko.com/grand-trail-des-cadourques-2027?currentPage=select-competition",
    },
    "klikego_bayeux_semi": {
        "plateforme": "klikego",
        "course": "Les Foulées de Bayeux 2027",
        "epreuve": "Semi Marathon Alain Buchart 21 km (21/03/2027)",
        "url": "https://www.klikego.com/inscription/les-foulees-de-bayeux-2027/running-course-a-pied/1714596490384-3",
    },
}

# Valeurs courtes et simples : holo4 n'a pas réussi à émettre "bloque_case_obligatoire"
# (session d56006bc, 11 essais de l'outil answer refusés) et a fini par répondre "echec".
Statut = Literal["PAIEMENT", "HUMAIN", "COMPTE", "CAPTCHA", "COMPLET", "ECHEC"]


class CaseSensible(BaseModel):
    texte: str = Field(description="Texte exact de la case ou du bloc")
    type: Literal["sante_pps_certificat", "reglement_cgv", "rgpd_image", "autre"]
    obligatoire: bool | None = None
    cochee: bool = Field(description="Doit rester false")


class ResultatInscription(BaseModel):
    course: str
    epreuve: str
    prix: str | None = Field(
        None, description="Prix affiché de l'épreuve, et total panier si visible"
    )
    champs_remplis: list[str] | None = None
    champs_manquants: list[str] = Field(
        description="Champs demandés sans valeur dans le profil, laissés vides"
    )
    cases_sensibles: list[CaseSensible]
    options_payantes_vues: list[str] | None = None
    url_finale: str
    statut: Statut = Field(
        description=(
            "PAIEMENT = arrêté juste avant paiement ; HUMAIN = case obligatoire à cocher par l'humain ; "
            "COMPTE = mot de passe/compte requis ; CAPTCHA ; COMPLET = épreuve fermée ; ECHEC = autre"
        )
    )
    commentaire: str = Field(description="Ce qui s'est passé, en une ou deux phrases")


def prompt(cible: dict) -> str:
    def lire(n: str) -> str:
        return (SKILLS / n).read_text(encoding="utf-8")

    return "\n\n".join(
        [
            (
                "Tu es l'agent d'inscription de RunAI. Tu prépares l'inscription d'une coureuse à une course, "
                "sans jamais payer ni soumettre définitivement. Un humain validera et paiera ensuite."
            ),
            f"Course : {cible['course']}\nÉpreuve : {cible['epreuve']}\nVa directement sur : {cible['url']}",
            lire("regles_communes.md"),
            lire(f"{cible['plateforme']}.md"),
            lire("profil_fictif.md"),
            (
                "Quand tu t'arrêtes, réponds avec le JSON demandé (statut, champs remplis, champs manquants, "
                "cases sensibles avec leur texte exact, url finale)."
            ),
        ]
    )


def attendre_quota(client: Client, max_s: int = 600) -> dict:
    debut = time.monotonic()
    while True:
        q = client.sessions.get_session_quota()
        info = {"limit": q.limit, "active": q.active, "available": q.available}
        print("quota", info, flush=True)
        if (q.available or 0) > 0:
            return {**info, "attente_s": round(time.monotonic() - debut)}
        if time.monotonic() - debut > max_s:
            raise SystemExit("Quota H toujours à 0 après 10 min : abandon.")
        time.sleep(60)


def main(nom: str) -> None:
    load_dotenv()
    cible = CIBLES[nom]
    client = Client()
    dossier = RESULTATS / nom
    (dossier / "captures").mkdir(parents=True, exist_ok=True)
    quota = attendre_quota(client)
    t0 = time.monotonic()
    handle = client.start_session(
        agent="h/web-surfer-pro",
        messages=prompt(cible),
        answer_schema=ResultatInscription,
        max_steps=80,
        max_time_s=1200,
        timezone="Europe/Paris",
        queue=False,
    )
    sid = handle.id
    print("session", sid, flush=True)
    res = None
    erreur = None
    brut = None
    try:
        res = wait_for_session(
            client, sid, timeout_seconds=1500, answer_schema=ResultatInscription
        )
    except AnswerValidationError as e:
        erreur, brut = repr(e), e.raw
    except Exception as e:  # noqa: BLE001
        erreur = repr(e)
    finally:
        duree = round(time.monotonic() - t0, 1)
        statut_avant = str(client.sessions.get_session_status(sid).status)
        try:
            handle.cancel()
            annulee = True
        except Exception as e:  # noqa: BLE001
            annulee = f"cancel: {e!r}"
    answer = res.answer if res else brut
    sauver(
        client, nom, sid, dossier, quota, duree, statut_avant, annulee, erreur, answer
    )


def sauver(
    client, nom, sid, dossier, quota, duree, statut_avant, annulee, erreur, answer
):
    cible = CIBLES[nom]
    items, page = [], 1
    while True:
        r = client.sessions.list_session_events(sid, page=page, size=100).model_dump()
        items += r["items"]
        if not r["items"] or len(items) >= r["total"]:
            break
        page += 1
    types: dict[str, int] = {}
    for it in items:
        types[it.get("type")] = types.get(it.get("type"), 0) + 1
    images: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "url" and str(o.get("media_type", "")).startswith(
                "image"
            ):
                images.append(o["source"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(items)
    captures = []
    hdr = {"Authorization": f"Bearer {os.environ['HAI_API_KEY']}"}
    n = len(images)
    choix = sorted({0, n // 3, (2 * n) // 3, n - 2, n - 1}) if n > 2 else range(n)
    for i in choix:
        try:
            r = httpx.get(images[i], headers=hdr, follow_redirects=True, timeout=30)
            if r.status_code == 200 and r.content:
                p = dossier / "captures" / f"capture_{i:02d}_sur_{n}.png"
                p.write_bytes(r.content)
                captures.append(p.name)
            else:
                print("capture", i, r.status_code)
        except Exception as e:  # noqa: BLE001
            print("capture", i, repr(e))
    sess = client.sessions.get_session(sid).model_dump()
    st = sess["status"]
    sortie = {
        "cible": nom,
        **cible,
        "session_id": sid,
        "agent": "h/web-surfer-pro",
        "quota_avant": quota,
        "created_at": str(sess.get("created_at")),
        "started_at": str(sess.get("started_at")),
        "finished_at": str(sess.get("finished_at")),
        "duree_client_s": duree,
        "statut_avant_cancel": statut_avant,
        "statut_final": st.get("status"),
        "outcome": st.get("outcome"),
        "erreur": erreur or st.get("error"),
        "etapes_h": st.get("steps"),
        "usage_tokens": st.get("usage_per_model"),
        "nb_evenements": len(items),
        "types_evenements": types,
        "nb_captures_disponibles": n,
        "captures": captures,
        "annulee": annulee,
        "answer": answer.model_dump() if hasattr(answer, "model_dump") else answer,
    }
    (dossier / "resultat.json").write_text(
        json.dumps(sortie, ensure_ascii=False, indent=2, default=str)
    )
    print(json.dumps(sortie, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    if sys.argv[1] == "recup":
        # Recollecte a posteriori : recup <cible> <session_id>
        load_dotenv()
        c = Client()
        nom, sid = sys.argv[2], sys.argv[3]
        dossier = RESULTATS / nom
        (dossier / "captures").mkdir(parents=True, exist_ok=True)
        brut = c.sessions.get_session_changes(sid, from_index=0).answer
        sauver(c, nom, sid, dossier, None, None, None, "deja annulee", None, brut)
    else:
        main(sys.argv[1])
