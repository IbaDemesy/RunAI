"""Build the sample GPX: hand-placed Lisbon waypoints, routed on OpenStreetMap.

Usage: python web/flyover/tools/build_sample_gpx.py
Network only (OSRM foot router of routing.openstreetmap.de, Open-Meteo elevation).
"""

from __future__ import annotations

import itertools
import math
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

OUTPUT = Path(__file__).resolve().parents[1] / "samples" / "lisbonne-collines-exemple.gpx"
ROUTER = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
ELEVATION = "https://api.open-meteo.com/v1/elevation"

# Hand-placed waypoints (lon, lat): a hilly loop from Praça do Comércio.
WAYPOINTS = [
    (-9.1366, 38.7077),  # Praça do Comércio
    (-9.1335, 38.7099),  # Sé
    (-9.1302, 38.7118),  # Miradouro de Santa Luzia
    (-9.1316, 38.7163),  # Graça
    (-9.1327, 38.7194),  # Senhora do Monte
    (-9.1360, 38.7160),  # Martim Moniz
    (-9.1458, 38.7213),  # Avenida da Liberdade
    (-9.1500, 38.7253),  # Marquês de Pombal
    (-9.1545, 38.7290),  # Parque Eduardo VII
    (-9.1543, 38.7200),  # Rato
    (-9.1490, 38.7165),  # Príncipe Real
    (-9.1441, 38.7155),  # São Pedro de Alcântara
    (-9.1420, 38.7107),  # Chiado
    (-9.1440, 38.7065),  # Cais do Sodré
    (-9.1366, 38.7077),  # Praça do Comércio
]
MIN_SPACING_M = 15.0


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def route(client: httpx.Client) -> list[tuple[float, float]]:
    coords = ";".join(f"{lon},{lat}" for lon, lat in WAYPOINTS)
    response = client.get(ROUTER + coords, params={"overview": "full", "geometries": "geojson"})
    response.raise_for_status()
    points = [tuple(p) for p in response.json()["routes"][0]["geometry"]["coordinates"]]
    kept = [points[0]]
    for point in points[1:-1]:
        if haversine(kept[-1], point) >= MIN_SPACING_M:
            kept.append(point)
    kept.append(points[-1])
    return kept


def elevations(client: httpx.Client, points: list[tuple[float, float]]) -> list[float]:
    result: list[float] = []
    for start in range(0, len(points), 100):
        chunk = points[start : start + 100]
        response = client.get(
            ELEVATION,
            params={
                "latitude": ",".join(f"{lat:.6f}" for _, lat in chunk),
                "longitude": ",".join(f"{lon:.6f}" for lon, _ in chunk),
            },
        )
        response.raise_for_status()
        result.extend(response.json()["elevation"])
    return result


def to_gpx(points: list[tuple[float, float]], eles: list[float]) -> str:
    trkpts = "\n".join(
        f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele></trkpt>'
        for (lon, lat), ele in zip(points, eles, strict=True)
    )
    name = "Lisbonne, boucle des collines (exemple)"
    desc = (
        "Parcours d'exemple placé à la main pour la démo RunAI, PAS un tracé officiel de course. "
        "Itinéraire calculé sur les données OpenStreetMap (ODbL) ; altitudes Open-Meteo (Copernicus DEM GLO-90)."
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="RunAI web/flyover/tools/build_sample_gpx.py" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>{escape(name)}</name>
    <desc>{escape(desc)}</desc>
    <copyright author="OpenStreetMap contributors">
      <year>{date.today().year}</year>
      <license>https://opendatacommons.org/licenses/odbl/1-0/</license>
    </copyright>
    <link href="https://www.openstreetmap.org/copyright"><text>© OpenStreetMap contributors</text></link>
  </metadata>
  <trk>
    <name>{escape(name)}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>
"""


def main() -> None:
    with httpx.Client(timeout=30) as client:
        points = route(client)
        eles = elevations(client, points)
    OUTPUT.write_text(to_gpx(points, eles), encoding="utf-8")
    length = sum(haversine(a, b) for a, b in itertools.pairwise(points))
    print(f"{OUTPUT.name}: {len(points)} points, {length / 1000:.2f} km, {min(eles):.0f}–{max(eles):.0f} m")


if __name__ == "__main__":
    main()
