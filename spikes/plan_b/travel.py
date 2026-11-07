"""Durées Paris -> ville (ESTIMÉES : horaires commerciaux typiques, trajet direct le plus rapide).

Train : meilleur TGV/Eurostar direct. Vol : temps bloc programmé CDG/ORY, aéroport le plus proche (via).
Ce n'est pas une recherche de billets : RunAI devra confirmer avec l'agent transport.
"""

from __future__ import annotations

import unicodedata

from models import TravelEstimate

MAX_MINUTES = 120

# clé normalisée -> (mode, minutes, via)
TRAVEL: dict[str, tuple[str, int, str | None]] = {
    "paris": ("local", 0, None), "saint-denis": ("local", 0, "Paris"), "boulogne-billancourt": ("local", 0, "Paris"),
    "vincennes": ("local", 0, "Paris"), "versailles": ("local", 0, "Paris"),
    "lille": ("train", 62, None), "lyon": ("train", 117, None), "rennes": ("train", 85, None),
    "strasbourg": ("train", 106, None), "reims": ("train", 46, None), "tours": ("train", 60, None),
    "le mans": ("train", 55, None), "metz": ("train", 82, None), "nancy": ("train", 90, None),
    "angers": ("train", 95, None), "dijon": ("train", 95, None), "orleans": ("train", 60, None),
    "rouen": ("train", 70, None), "amiens": ("train", 65, None), "arras": ("train", 50, None),
    "bruxelles": ("train", 82, None), "brussels": ("train", 82, None), "anvers": ("train", 120, None),
    "antwerp": ("train", 120, None), "luxembourg": ("flight", 60, None), "london": ("flight", 75, None),
    "londres": ("flight", 75, None), "east molesey": ("flight", 75, "Londres"), "amsterdam": ("flight", 80, None),
    "the hague": ("flight", 80, "Amsterdam"), "den haag": ("flight", 80, "Amsterdam"), "la haye": ("flight", 80, "Amsterdam"),
    "rotterdam": ("flight", 75, None), "eindhoven": ("flight", 70, None), "marseille": ("flight", 80, None),
    "nice": ("flight", 85, None), "toulouse": ("flight", 75, None), "montpellier": ("flight", 80, None),
    "bordeaux": ("flight", 70, None), "nantes": ("flight", 60, None), "biarritz": ("flight", 75, None),
    "irun": ("flight", 75, "Biarritz"), "san sebastian": ("flight", 75, "Biarritz"), "bilbao": ("flight", 90, None),
    "barcelona": ("flight", 100, None), "barcelone": ("flight", 100, None), "valencia": ("flight", 115, None),
    "palma": ("flight", 110, None), "madrid": ("flight", 125, None), "malaga": ("flight", 160, None),
    "sevilla": ("flight", 150, None), "seville": ("flight", 150, None), "lisbon": ("flight", 145, None),
    "lisboa": ("flight", 145, None), "lisbonne": ("flight", 145, None), "porto": ("flight", 130, None),
    "vila nova de gaia": ("flight", 130, "Porto"), "milan": ("flight", 90, None), "milano": ("flight", 90, None),
    "turin": ("flight", 85, None), "torino": ("flight", 85, None), "venice": ("flight", 100, None),
    "venezia": ("flight", 100, None), "bologna": ("flight", 100, None), "modena": ("flight", 100, "Bologne"),
    "florence": ("flight", 110, None), "firenze": ("flight", 110, None), "pisa": ("flight", 110, None),
    "rome": ("flight", 125, None), "roma": ("flight", 125, None), "ostia": ("flight", 125, "Rome"),
    "naples": ("flight", 140, None), "napoli": ("flight", 140, None), "geneva": ("flight", 65, None),
    "geneve": ("flight", 65, None), "lausanne": ("flight", 65, "Genève"), "zurich": ("flight", 75, None),
    "basel": ("flight", 65, None), "bale": ("flight", 65, None), "frankfurt": ("flight", 75, None),
    "cologne": ("flight", 70, None), "koln": ("flight", 70, None), "dusseldorf": ("flight", 75, None),
    "stuttgart": ("flight", 75, None), "munich": ("flight", 95, None), "munchen": ("flight", 95, None),
    "hamburg": ("flight", 95, None), "berlin": ("flight", 115, None), "copenhagen": ("flight", 115, None),
    "kobenhavn": ("flight", 115, None), "prague": ("flight", 105, None), "praha": ("flight", 105, None),
    "vienna": ("flight", 125, None), "wien": ("flight", 125, None), "dublin": ("flight", 95, None),
    "cork": ("flight", 105, None), "edinburgh": ("flight", 110, None), "glasgow": ("flight", 115, None),
    "manchester": ("flight", 90, None), "liverpool": ("flight", 90, None), "birmingham": ("flight", 85, None),
    "bristol": ("flight", 80, None), "bath": ("flight", 80, "Bristol"), "blackpool": ("flight", 90, "Manchester"),
    "cardiff": ("flight", 80, "Bristol"), "ghent": ("train", 115, "Bruxelles"), "gent": ("train", 115, "Bruxelles"),
    "gand": ("train", 115, "Bruxelles"), "amstelveen": ("flight", 80, "Amsterdam"), "verona": ("flight", 100, None),
    "avignon": ("train", 160, None), "zoetermeer": ("flight", 80, "Amsterdam"), "utrecht": ("flight", 80, "Amsterdam"),
    "leiden": ("flight", 80, "Amsterdam"), "granollers": ("flight", 100, "Barcelone"), "cambridge": ("flight", 75, "Londres"),
    "reggio emilia": ("flight", 100, "Bologne"), "castellon": ("flight", 115, "Valence"), "tarragona": ("flight", 100, "Barcelone"),
    "monza": ("flight", 90, "Milan"), "bergamo": ("flight", 90, None), "brescia": ("flight", 90, "Milan"), "padova": ("flight", 100, "Venise"),
    "treviso": ("flight", 100, "Venise"), "genova": ("flight", 90, None), "berlin mitte": ("flight", 115, None), "haarlem": ("flight", 80, "Amsterdam"), "brugge": ("train", 150, None), "warsaw": ("flight", 140, None), "budapest": ("flight", 140, None),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace(",", " ").split())


_KEYS = sorted(((norm(k), v) for k, v in TRAVEL.items()), key=lambda kv: -len(kv[0]))


def lookup(city: str | None) -> TravelEstimate | None:
    if not city:
        return None
    c = f" {norm(city)} "
    for key, (mode, minutes, via) in _KEYS:
        if f" {key} " in c:
            return TravelEstimate(mode=mode, minutes=minutes, via=via)
    return None
