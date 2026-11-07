"""Estimateur de niveau déterministe (pas de LLM) : formule de Riegel + heuristiques de volume.

Entrée : JSON « profil coureur » venant de la déclaration vocale, d'un fichier, ou (hors démo, voir
README) de l'API Strava. Sortie : niveau, prédictions de chrono, semaines de préparation minimales.
"""

from __future__ import annotations

import json
import sys

DISTANCES_M = {"5K": 5000, "10K": 10000, "Semi": 21097.5, "Marathon": 42195}
EXPOSANT_RIEGEL = 1.06


def riegel(temps_s: float, d1_m: float, d2_m: float) -> float:
    return temps_s * (d2_m / d1_m) ** EXPOSANT_RIEGEL


def _hms(s: float) -> str:
    s = round(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def semaines_preparation_min(distance_km: float, niveau: str = "intermediaire", d_plus_m: float = 0) -> int:
    base = 6 if distance_km <= 10 else 10 if distance_km <= 21.1 else 16
    if d_plus_m >= 1000:
        base += 4
    if niveau == "debutant":
        base += 4
    elif niveau == "confirme":
        base -= 2
    return max(base, 4)


def estimer(profil: dict) -> dict:
    """profil : sorties_par_semaine, plus_longue_sortie_km, km_par_semaine?, meilleurs_efforts?
    [{distance_m, temps_s, date}], chrono_declare? {distance_m, temps_s}, envies?"""
    efforts = list(profil.get("meilleurs_efforts", []))
    if profil.get("chrono_declare"):
        efforts.append({**profil["chrono_declare"], "source": "declaration"})
    efforts = [e for e in efforts if e.get("distance_m", 0) >= 3000]
    hypotheses = []
    if efforts:
        ref = min(efforts, key=lambda e: riegel(e["temps_s"], e["distance_m"], 10000))
        t10 = riegel(ref["temps_s"], ref["distance_m"], 10000)
        base = f"{ref['distance_m'] / 1000:g} km en {_hms(ref['temps_s'])}"
    else:
        allure = 7.0 if profil.get("sorties_par_semaine", 0) < 2 else 6.25
        t10 = allure * 60 * 10
        base = "aucun chrono : allure prudente supposée"
        hypotheses.append(f"aucun chrono, 10 km estimé à {allure:g} min/km d'après la fréquence")
    longue = profil.get("plus_longue_sortie_km", 0)
    sorties = profil.get("sorties_par_semaine", 0)
    if t10 > 60 * 60 or sorties < 2 or longue < 8:
        niveau = "debutant"
    elif t10 < 42 * 60 and sorties >= 4 and longue >= 15:
        niveau = "confirme"
    else:
        niveau = "intermediaire"
    predictions = {}
    for nom, d in DISTANCES_M.items():
        fiable = longue >= {"5K": 3, "10K": 7, "Semi": 14, "Marathon": 25}[nom]
        predictions[nom] = {"temps": _hms(riegel(t10, 10000, d)), "fiable": fiable}
    distances_ok = [nom for nom, p in predictions.items() if p["fiable"]]
    return {
        "niveau": niveau,
        "base": base,
        "equivalent_10k": _hms(t10),
        "predictions": predictions,
        "distances_conseillees": distances_ok or ["5K"],
        "semaines_preparation_min": {nom: semaines_preparation_min(d / 1000, niveau) for nom, d in DISTANCES_M.items()},
        "hypotheses": hypotheses,
    }


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(estimer(json.load(f)), ensure_ascii=False, indent=2))
