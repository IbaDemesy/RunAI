"""PB-04 / AC-01: owned Explore copy must remain English (source names are data)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", [
    "web/flyover/journey-fallback.js", "web/flyover/journey-player.js", "web/flyover/flyover.js",
    "web/flyover/route.js", "web/flyover/index.html", "runai/app/static/journey-view.js",
])
def test_j5_explore_english_only(name):
    text = (ROOT / name).read_text()
    french_copy = re.compile(
        r"Séjour|séjour|Vérifié|géométrie|Approximatif|Illustratif|Démonstration|Préparation|"
        r"Prix inconnu|Horaire non renseigné|Plafond|Mouvement réduit|Carte indisponible|"
        r"Chapitre inconnu|Vue détruite|Aucun chapitre|Kilomètre invalide|Tracé de course|"
        r"Départ|Arrivée|▶ Lecture|Parcours sans nom|Impossible de charger|Chargement|"
        r"Durée du survol|Vue d'ensemble|Ouvrir un GPX|Aucun tracé exploitable|lang=\"fr\""
    )
    assert not french_copy.search(text)


def test_j11_new_jury_audit_notes_are_english():
    text = (ROOT / "docs" / "NOTATION.md").read_text()
    assert not re.search(r"Revue du code le|Intégration H présente|orchestrateur présents|Partiel :|contrôle navigateur", text)
    assert "Code review on" in text
