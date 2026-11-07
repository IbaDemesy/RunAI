"""Prompts H « devis » par plateforme, prêts à lancer. Par défaut : dry-run (aucune session H).

    python spikes/tarifs_options/h_devis.py klikego <url> "Marathon"           # affiche le payload
    python spikes/tarifs_options/h_devis.py njuko <url> "10 km" --run          # lance 1 session H

--run vérifie le quota (attente max 10 min, re-check 60 s), lance UNE session et l'annule
toujours à la fin (finally), même en cas d'erreur.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from devis_schema import Devis, verifier_devis

AGENT = "h/web-surfer-pro"
PROFIL_FICTIF = (
    "Camille Martin, femme, née le 12/05/1994, nationalité française, e-mail camille.martin@example.com, "
    "téléphone +33 6 00 00 00 00, 10 rue de l'Exemple 75011 Paris, non licenciée, sans club."
)
REGLES = """RÈGLES ABSOLUES :
- Ne paie jamais, ne soumets aucun formulaire de manière définitive, ne crée aucun compte, ne saisis aucun mot de passe.
- Ne coche aucune case de règlement, CGU, RGPD, santé, certificat médical ou PPS : arrête-toi devant.
- N'utilise que le profil fictif fourni. Si un vrai e-mail ou un compte est exigé, arrête-toi et dis-le.
- Ne sélectionne aucune option payante : relève-les seulement.
- Si une information n'est pas affichée, mets null ; n'invente jamais un prix ou une date.
- total_minimal_eur = prix du palier actuel + frais de service s'ils ne sont pas inclus + options obligatoires.
- Mets rien_soumis=true si et seulement si tu n'as rien soumis."""

TACHES = {
    "njuko": """Ouvre {url}. Tu es sur une billetterie njuko. Pour l'épreuve « {epreuve} » :
1. Refuse les cookies, puis lis la carte de l'épreuve : tarif par personne, texte sur les frais de service, date/heure, complet ou non. Survole une éventuelle icône d'info pour voir les paliers suivants.
2. Clique « S'INSCRIRE » sur cette épreuve et remplis seulement les champs d'identité avec : {profil}
3. Passe à l'étape suivante seulement si la page ne contient aucune case de consentement, santé ou paiement. Continue ainsi jusqu'aux étapes « Services » / « Insurance » si c'est possible, en relevant chaque option payante (nom, prix, obligatoire ?).
4. Arrête-toi au premier blocage (case de consentement, compte, paiement) ou au panier, et rends le devis.""",
    "klikego": """Ouvre {url}. Tu es sur une page d'événement Klikego. Pour l'épreuve « {epreuve} » :
1. Clique sur la tuile de l'épreuve (pas sur « S'inscrire ») pour ouvrir le détail des tarifs : relève chaque tarif (palier, tarif licencié/non licencié, dernière minute et sa date), et les frais de gestion Internet affichés.
2. Ferme le détail et lis la description de l'événement pour relever les options payantes (t-shirt, repas, assurance annulation, navette, photos, dons) avec leur prix.
3. Ne clique pas « S'inscrire » : l'étape suivante crée un compte Klikego. Arrête-toi ici (etape_arret="fiche_epreuve") et rends le devis pour un coureur non licencié.""",
}


def construire(plateforme: str, url: str, epreuve: str) -> dict:
    tache = TACHES[plateforme].format(url=url, epreuve=epreuve, profil=PROFIL_FICTIF)
    return {
        "agent": AGENT,
        "messages": f"{tache}\n\n{REGLES}",
        "overrides": {"agent.environments[kind=web].start_url": url},
        "max_steps": 45 if plateforme == "njuko" else 25,
        "max_time_s": 600,
    }


def attendre_slot(client) -> None:
    for i in range(11):
        q = client.sessions.get_session_quota()
        print(f"quota H : {q.active}/{q.limit} actifs, {q.available} libres")
        if q.available > 0:
            return
        if i < 10:
            time.sleep(60)
    raise SystemExit("aucun slot H libre après 10 min : abandon")


def lancer(payload: dict) -> None:
    from dotenv import load_dotenv
    from hai_agents import Client

    load_dotenv()
    client = Client()
    attendre_slot(client)
    t0 = time.monotonic()
    handle = client.start_session(answer_schema=Devis, **payload)
    print(f"session H : {handle.id}")
    try:
        res = handle.wait_for_completion(timeout_seconds=payload["max_time_s"] + 60)
        print(f"statut={res.status} durée={time.monotonic() - t0:.0f}s")
        if isinstance(res.answer, Devis):
            print(res.answer.model_dump_json(indent=2))
            for a in verifier_devis(res.answer):
                print("ALERTE :", a)
        else:
            print(res.answer)
    finally:
        try:
            handle.cancel()
            print("session annulée (slot libéré)")
        except Exception as exc:  # noqa: BLE001 - session déjà terminée : rien à libérer
            print(f"cancel : {exc}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plateforme", choices=sorted(TACHES))
    ap.add_argument("url")
    ap.add_argument("epreuve")
    ap.add_argument(
        "--run",
        action="store_true",
        help="lance vraiment une session H (consomme 1 slot)",
    )
    a = ap.parse_args()
    payload = construire(a.plateforme, a.url, a.epreuve)
    if not a.run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(
            "\n(dry-run : ajouter --run pour lancer 1 session H, answer_schema=Devis)"
        )
        return
    lancer(payload)


if __name__ == "__main__":
    main()
