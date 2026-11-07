import itertools
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLYOVER = ROOT / "web" / "flyover"
SAMPLE = FLYOVER / "samples" / "lisbonne-collines-exemple.gpx"
GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


def _haversine(a, b):
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * asin(sqrt(h))


def test_sample_gpx_is_a_licensed_example_track_with_elevation():
    root = ET.parse(SAMPLE).getroot()
    metadata = root.find("gpx:metadata", GPX_NS)
    assert "exemple" in metadata.findtext("gpx:name", namespaces=GPX_NS)
    assert "PAS un tracé officiel" in metadata.findtext("gpx:desc", namespaces=GPX_NS)
    assert "odbl" in metadata.findtext("gpx:copyright/gpx:license", namespaces=GPX_NS)

    points = root.findall(".//gpx:trkpt", GPX_NS)
    assert len(points) > 100
    assert all(point.findtext("gpx:ele", namespaces=GPX_NS) for point in points)
    coords = [(float(p.get("lat")), float(p.get("lon"))) for p in points]
    length = sum(_haversine(a, b) for a, b in itertools.pairwise(coords))
    assert 9_000 < length < 11_000


def test_page_pins_maplibre_with_sri_and_uses_no_api_key():
    html = (FLYOVER / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'(?:src|href)="(https://[^"]+)"\s+integrity="sha384-[^"]+"', html)
    assert sorted(assets) == [
        "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css",
        "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js",
    ]
    script = (FLYOVER / "flyover.js").read_text(encoding="utf-8")
    assert not re.search(r"(api[_-]?key|access_token|key=)", html + script, re.IGNORECASE)


def test_every_tile_source_declares_its_attribution():
    script = (FLYOVER / "flyover.js").read_text(encoding="utf-8")
    sources = re.findall(r"\n        (\w+): \{\n          type: \"(?:raster|raster-dem)\"", script)
    assert sorted(sources) == ["hillshade", "osm", "satellite", "terrain"]
    for needle in ("tiles.mapterhorn.com", "openstreetmap.org/copyright", "s2maps.eu", "AttributionControl"):
        assert needle in script
    assert script.count("attribution:") == len(sources)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent : tests JS du survol non lancés")
def test_flyover_javascript_unit_tests():
    result = subprocess.run(
        ["node", "--test", str(FLYOVER / "tests" / "route.test.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
