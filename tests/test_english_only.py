"""PB-04 / AC-05: owned Explore copy must remain English (source names are data)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["journey-fallback.js", "journey-player.js", "flyover.js", "index.html"])
def test_j5_explore_english_only(name):
    text = (ROOT / "web" / "flyover" / name).read_text()
    french_copy = re.compile(
        r"Séjour|séjour|Vérifié|géométrie|Approximatif|Illustratif|Démonstration|Préparation|"
        r"Prix inconnu|Horaire non renseigné|Plafond|Mouvement réduit|Carte indisponible|"
        r"Chapitre inconnu|Vue détruite|Aucun chapitre|Kilomètre invalide|Tracé de course|"
        r"Départ|Arrivée|▶ Lecture|Parcours sans nom|Impossible de charger|Chargement|"
        r"Durée du survol|Vue d'ensemble|Ouvrir un GPX|lang=\"fr\""
    )
    assert not french_copy.search(text)
