"""Préréglages de démo : préférences dont le résultat Linkup est livré dans `fixtures/`.

`recommend_races(assessment, DEMO_PREFERENCES["milan"], mode="replay")` rejoue sans réseau.
"""

from datetime import date

from runai.coach.models import RacePreferences

DEMO_TRANSCRIPT = (
    "Je cours quatre fois par semaine, à peu près quarante kilomètres. "
    "Ma plus longue sortie c'est 22 km en 2h05. "
    "J'ai fait le semi de Boulogne en 1h48 il y a 3 mois. "
    "Je cours depuis 3 ans et j'ai 31 ans. "
    "J'aimerais courir mon premier marathon en voyage, à l'étranger."
)

DEMO_PREFERENCES: dict[str, RacePreferences] = {
    # Course de démo retenue : Wizz Air Milano Marathon (04/04/2027, inscription Njuko).
    "milan": RacePreferences(
        origin_city="Paris",
        date_from=date(2027, 3, 1),
        date_to=date(2027, 5, 31),
        distance_km=42.195,
        terrain="plat",
        race_size="grande",
        max_travel_h=2.5,
        travel_mode="flight",
        foreign=True,
        zone_hint="en Europe hors de France (Italie, Espagne, Portugal, Belgique, Pays-Bas, Allemagne)",
        seed_races=["Wizz Air Milano Marathon"],
    ),
    # Les 4 profils mesurés du spike trouver_courses (07/11/2026).
    "debutant_10k_paris": RacePreferences(
        origin_city="Paris",
        date_from=date(2027, 3, 1),
        date_to=date(2027, 4, 30),
        distance_km=10,
        terrain="plat",
        max_travel_h=1.5,
        zone_hint="en Ile-de-France (Paris et alentours)",
    ),
    "semi_france": RacePreferences(
        origin_city="Paris",
        date_from=date(2027, 3, 1),
        date_to=date(2027, 5, 31),
        distance_km=21.0975,
        terrain="plat",
        race_size="grande",
        max_travel_h=5,
        zone_hint="en France",
    ),
    "trail_lyon": RacePreferences(
        origin_city="Lyon",
        date_from=date(2027, 4, 1),
        date_to=date(2027, 6, 30),
        distance_km=25,
        distance_tolerance_km=6,
        trail=True,
        terrain="vallonne",
        max_travel_h=3,
        zone_hint="en Auvergne-Rhone-Alpes, Bourgogne ou Jura (moins de 3 h de Lyon)",
    ),
    "semi_etranger": RacePreferences(
        origin_city="Paris",
        date_from=date(2027, 3, 1),
        date_to=date(2027, 5, 31),
        distance_km=21.0975,
        terrain="plat",
        race_size="grande",
        max_travel_h=2,
        travel_mode="flight",
        foreign=True,
        zone_hint="en Europe hors de France (Espagne, Portugal, Italie, Belgique, Pays-Bas, Allemagne, Royaume-Uni, Irlande, Danemark...)",
    ),
}
