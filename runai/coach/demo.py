"""Demo preferences whose Linkup results are bundled in `fixtures/`.

`recommend_races(assessment, DEMO_PREFERENCES["milan"], mode="replay")` runs offline.
"""

from datetime import date

from runai.coach.models import RacePreferences

DEMO_TRANSCRIPT = (
    "I run four times a week, roughly forty kilometres. "
    "My longest run was 22 km in 2h05. "
    "I ran the Boulogne half marathon in 1h48 3 months ago. "
    "I have been running for 3 years and I am 31. "
    "I'd like to run my first marathon while travelling abroad."
)

DEMO_PREFERENCES: dict[str, RacePreferences] = {
    # Selected demo race: Wizz Air Milano Marathon (04/04/2027, Njuko registration).
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
    # Four measured profiles from the race-finding spike (07/11/2026).
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
