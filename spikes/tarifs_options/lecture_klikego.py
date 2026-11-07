"""Devis Klikego SANS session H : page événement + fiche épreuve (/v8/evenement/epreuve.jsp), GET uniquement.

    python spikes/tarifs_options/lecture_klikego.py <url_evenement_klikego> [filtre_epreuve]

On ne touche à aucune page interdite par robots.txt (formulaire, panier, paiement).
Les options payantes sont dans le texte libre de la description : on les extrait par mots-clés (indicatif).
"""

from __future__ import annotations

import re
import sys
import urllib.request
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from devis_schema import Devis, OptionPayante, Palier, verifier_devis

OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
OPENER.addheaders = [("User-Agent", "Mozilla/5.0 (RunAI spike lecture seule)")]
EUR = r"(\d+(?:[.,]\d+)?)\s*€"
MOTS_OPTIONS = [
    ("assurance_annulation", r"assurance annulation|garantie annulation"),
    ("t_shirt", r"t-shirt|tee-shirt"),
    ("repas", r"repas|pasta"),
    ("navette", r"navette"),
    ("photos", r"photos?\b"),
    ("don", r"\bdons?\b"),
]


def _get(url: str) -> str:
    with OPENER.open(url, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _txt(s: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.DOTALL)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _options(desc: str) -> list[OptionPayante]:
    out = []
    for cat, pat in MOTS_OPTIONS:
        for m in re.finditer(pat, desc, re.IGNORECASE):
            fen = desc[m.start() : m.start() + 260]
            p = re.search(EUR, fen)
            out.append(
                OptionPayante(
                    nom=fen[:80],
                    categorie=cat,
                    prix_eur=_f(p.group(1)) if p else None,
                    obligatoire=False,
                    etape="formulaire (après création du compte)",
                )
            )
            break
    return out


def devis(url: str, filtre: str | None = None) -> list[Devis]:
    raw = _get(url)
    ev = re.search(r"evenement/epreuve\.jsp\?embedded=1&e=([\d-]+)", raw).group(1)
    course = _txt(re.search(r"<title>(.*?)</title>", raw, re.DOTALL).group(1)).split(
        " | "
    )[0]
    heats = re.findall(r"heatDetails\('(\d+)'\)", raw)
    noms = re.findall(r'<h3 class="flex-1[^"]*">([^<]+)</h3>', raw)
    options = _options(_txt(raw))
    out = []
    for heat, nom in zip(heats, noms):
        nom = _txt(nom)
        if filtre and filtre.lower() not in nom.lower():
            continue
        fiche = _txt(
            _get(
                f"https://www.klikego.com/v8/evenement/epreuve.jsp?embedded=1&e={ev}&heat={heat}"
            )
        )
        tarifs = re.findall(
            r"(Droits? d'inscription|Tarif[^:]{0,40}|Inscriptions dernière minute)\s*:\s*"
            + EUR,
            fiche,
        )
        frais = re.search(EUR.replace(r"\s*€", r"\s*€ de frais de gestion"), fiche)
        complet = "Bourse d'échange" in fiche and "S'inscrire" not in fiche
        if not tarifs:
            continue
        nl = (
            [t for t in tarifs if "Non-Licenci" in t[0]]
            or [t for t in tarifs if "dernière minute" not in t[0]]
            or tarifs
        )
        actuel = nl[0]
        suivants = [
            Palier(prix_eur=_f(p), libelle=lib)
            for lib, p in tarifs
            if (lib, p) != actuel
        ]
        fr = _f(frais.group(1)) if frais else None
        alertes = (
            ["date de fin de palier non affichée sur la fiche"]
            if any("dernière minute" in t[0] for t in tarifs)
            else []
        )
        out.append(
            Devis(
                plateforme="klikego",
                course=course,
                epreuve=nom,
                url=url,
                palier_actuel=Palier(prix_eur=_f(actuel[1]), libelle=actuel[0]),
                paliers_suivants=suivants,
                frais_service_eur=fr,
                frais_inclus_dans_prix=False if fr is not None else None,
                options=options,
                total_minimal_eur=_f(actuel[1]) + (fr or 0),
                complet=complet,
                etape_arret="fiche_epreuve",
                raison_arret="lecture HTTP de la fiche épreuve ; l'étape suivante crée un compte Klikego",
                rien_soumis=True,
                avertissements=alertes,
            )
        )
    return out


if __name__ == "__main__":
    for d in devis(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None):
        print(d.model_dump_json(indent=1))
        for a in verifier_devis(d):
            print("  ALERTE :", a)
