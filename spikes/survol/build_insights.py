"""Construit data/course.json : trace reechantillonne, altitudes, D+ corrige, cotes,
ravitos, allure par km et trajets du week-end. Tout est calcule localement, sauf
l'altitude (Open-Meteo, MNT Copernicus 90 m, sans cle) et les trajets routiers (OSRM).

Usage : python spikes/survol/build_insights.py data/trace.kml [--objectif 1:45:00]
        python spikes/survol/build_insights.py --fallback          (sans trace)
"""

import argparse
import itertools
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

DATA = Path(__file__).parent / "data"
STEP_M = 25.0
UA = {"User-Agent": "RunAI-spike/0.1 (hackathon)"}

# Lieux du week-end (geocodes Nominatim le 2026-11-07). Hotel = exemple Accor du test H.
WEEKEND = {
    "gare": {
        "nom": "Aeroporto Humberto Delgado (LIS)",
        "lon": -9.13186,
        "lat": 38.78100,
    },
    "retrait": {
        "nom": "Retrait dossards - Centro de Congressos de Lisboa",
        "lon": -9.18425,
        "lat": 38.69894,
    },
    "hotel": {"nom": "ibis Lisboa José Malhoa", "lon": -9.16280, "lat": 38.73718},
}
WEEKENDS = {
    "lisbonne": WEEKEND,
    "milan": {
        "gare": {"nom": "Milano Centrale", "lon": 9.20426, "lat": 45.48588},
        "retrait": {
            "nom": "Retrait dossards - Allianz MiCo (lieu suppose, a confirmer)",
            "lon": 9.15308,
            "lat": 45.48058,
        },
        "hotel": {"nom": "ibis Milano Centro", "lon": 9.20178, "lat": 45.47829},
    },
}
# Fallback sans trace : depart / arrivee seuls (placemarks Partida et Meta du KML 2026).
FALLBACK_POINTS = {
    "depart": {
        "nom": "Départ (Ponte 25 de Abril, côté Almada)",
        "lon": -9.174854,
        "lat": 38.679501,
    },
    "arrivee": {"nom": "Arrivée (Belém)", "lon": -9.207188, "lat": 38.695744},
}
# Reglement 2027 : un ravitaillement tous les 5 km (positions estimees).
RAVITOS_REGLEMENT = [5, 10, 15, 20]


def hav(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def parse_trace(path):
    txt = Path(path).read_text(encoding="utf-8")
    root = ET.fromstring(txt.encode())
    for el in root.iter():
        el.tag = el.tag.split("}")[-1]
    lines, points = [], []
    if root.tag == "gpx":
        seg = [(float(p.get("lon")), float(p.get("lat"))) for p in root.iter("trkpt")]
        seg = seg or [
            (float(p.get("lon")), float(p.get("lat"))) for p in root.iter("rtept")
        ]
        lines.append(("gpx", seg))
        for w in root.iter("wpt"):
            points.append(
                {
                    "nom": (w.findtext("name") or "").strip(),
                    "lon": float(w.get("lon")),
                    "lat": float(w.get("lat")),
                }
            )
    else:
        for pm in root.iter("Placemark"):
            name = (pm.findtext("name") or "").strip()
            ls = pm.find(".//LineString/coordinates")
            pt = pm.find(".//Point/coordinates")
            if ls is not None:
                coords = [tuple(map(float, c.split(",")[:2])) for c in ls.text.split()]
                lines.append((name, coords))
            elif pt is not None:
                lon, lat = map(float, pt.text.strip().split(",")[:2])
                desc = re.sub(r"<[^>]+>", " ", pm.findtext("description") or "").strip()
                points.append({"nom": name, "desc": desc, "lon": lon, "lat": lat})
    name, line = max(lines, key=lambda nl: len(nl[1]))
    return name, line, points


def resample(line):
    cum = [0.0]
    for a, b in itertools.pairwise(line):
        cum.append(cum[-1] + hav(a, b))
    total = cum[-1]
    out, j, d = [], 0, 0.0
    while d <= total:
        while cum[j + 1] < d:
            j += 1
        seg = cum[j + 1] - cum[j] or 1
        t = (d - cum[j]) / seg
        a, b = line[j], line[j + 1]
        out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), d))
        d += STEP_M
    out.append((line[-1][0], line[-1][1], total))
    return out, total


def elevations_terrarium(pts, cache, z=14):
    """Altitude decodee localement depuis les tuiles terrarium Mapterhorn (meme MNT que le
    relief 3D de la carte) : h = R*256 + G + B/256 - 32768, interpolation bilineaire."""
    from io import BytesIO

    from PIL import Image

    if cache.exists():
        c = json.loads(cache.read_text())
        if len(c) == len(pts):
            return c, 0.0, 0
    t0, tiles, ele, size = time.time(), {}, [], 512
    n = 2**z
    with httpx.Client(timeout=30, headers=UA) as cl:
        for lon, lat, _ in pts:
            x = (lon + 180) / 360 * n
            y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
            tx, ty = int(x), int(y)
            if (tx, ty) not in tiles:
                r = cl.get(f"https://tiles.mapterhorn.com/{z}/{tx}/{ty}.webp")
                r.raise_for_status()
                tiles[(tx, ty)] = Image.open(BytesIO(r.content)).convert("RGB")
            im = tiles[(tx, ty)]
            px, py = (x - tx) * size - 0.5, (y - ty) * size - 0.5
            x0, y0 = max(0, min(size - 2, int(px))), max(0, min(size - 2, int(py)))
            fx, fy = min(1, max(0, px - x0)), min(1, max(0, py - y0))

            def h(i, j, im=im):
                r_, g_, b_ = im.getpixel((i, j))
                return r_ * 256 + g_ + b_ / 256 - 32768

            top = h(x0, y0) * (1 - fx) + h(x0 + 1, y0) * fx
            bot = h(x0, y0 + 1) * (1 - fx) + h(x0 + 1, y0 + 1) * fx
            ele.append(round(top * (1 - fy) + bot * fy, 2))
    cache.write_text(json.dumps(ele))
    return ele, time.time() - t0, len(tiles)


def elevations(pts, cache):
    if cache.exists():
        c = json.loads(cache.read_text())
        if len(c) == len(pts):
            return c, 0.0
    t0, ele = time.time(), []
    with httpx.Client(timeout=30) as cl:
        for i in range(0, len(pts), 100):
            chunk = pts[i : i + 100]
            r = cl.get(
                "https://api.open-meteo.com/v1/elevation",
                params={
                    "latitude": ",".join(f"{p[1]:.6f}" for p in chunk),
                    "longitude": ",".join(f"{p[0]:.6f}" for p in chunk),
                },
            )
            if r.status_code == 429:
                time.sleep(65)
                r = cl.get(r.url)
            r.raise_for_status()
            ele += r.json()["elevation"]
            time.sleep(2)
    cache.write_text(json.dumps(ele))
    return ele, time.time() - t0


def correct_jumps(ele, max_grade=0.12, max_span_m=4000):
    """Detecte les sauts du MNT sur les ouvrages et les remplace par un tablier droit.

    Un saut = |pente| > max_grade sur un pas de 25 m. Descente brutale = pont (le MNT
    voit l'eau ou la vallee sous le tablier) ; montee brutale = tunnel (le MNT voit la
    colline). Le tablier relie le bord avant le saut au point de sortie qui donne la
    pente la plus faible, tous les points intermediaires restant sous (pont) ou au-dessus
    (tunnel) de cette corde, a moins de max_span_m. Sans sortie plausible : pas de
    correction (c'est une vraie cote)."""
    n, e = len(ele), list(ele)
    max_k = int(max_span_m / STEP_M)
    fixes, a = [], 1
    while a < n:
        step = ele[a] - ele[a - 1]
        if abs(step) / STEP_M <= max_grade:
            a += 1
            continue
        sign, l, best = (1 if step > 0 else -1), a - 1, None
        for r in range(a + 1, min(n, l + max_k)):
            grade = (ele[r] - ele[l]) / (r - l)
            inner = [ele[k] - (ele[l] + grade * (k - l)) for k in range(l + 1, r)]
            # pont : tout l'interieur sous la corde ; tunnel : tout au-dessus
            if (sign < 0 and max(inner) > 0) or (sign > 0 and min(inner) < 0):
                continue
            depth = -min(inner) if sign < 0 else max(inner)
            if (
                depth >= 10
                and abs(grade) / STEP_M <= 0.06
                and (best is None or abs(grade) < best[1])
            ):
                best = (r, abs(grade))
        if best is None:
            a += 1
            continue
        r = best[0]
        for k in range(l + 1, r):
            e[k] = ele[l] + (ele[r] - ele[l]) * (k - l) / (r - l)
        fixes.append({"type": "pont" if sign < 0 else "tunnel", "i0": l, "i1": r})
        a = r + 1
    return e, fixes


def smooth(e, win_m=150):
    k = max(1, int(win_m / STEP_M / 2))
    return [
        sum(e[max(0, i - k) : i + k + 1]) / len(e[max(0, i - k) : i + k + 1])
        for i in range(len(e))
    ]


def gain(e, hyst=1.0):
    up = down = 0.0
    ref = e[0]
    for x in e[1:]:
        if x - ref >= hyst:
            up += x - ref
            ref = x
        elif ref - x >= hyst:
            down += ref - x
            ref = x
    return round(up), round(down)


def climbs(d, e, min_len=300, min_grade=0.025):
    out, i, n = [], 0, len(e)
    w = int(100 / STEP_M)
    g = [
        (e[min(n - 1, j + w)] - e[j]) / (d[min(n - 1, j + w)] - d[j] or 1)
        for j in range(n)
    ]
    while i < n:
        if g[i] >= min_grade:
            j = i
            while j < n and g[j] >= min_grade * 0.6:
                j += 1
            j = min(j + w, n - 1)
            if d[j] - d[i] >= min_len:
                out.append(
                    {
                        "km_debut": round(d[i] / 1000, 2),
                        "km_fin": round(d[j] / 1000, 2),
                        "d_plus": round(e[j] - e[i]),
                        "pente_moy": round(100 * (e[j] - e[i]) / (d[j] - d[i]), 1),
                    }
                )
            i = j + 1
        else:
            i += 1
    return out


def pace_plan(d, e, total_m, objectif_s):
    """Allure par km : temps(km) = base * (1 + 0.033*pente_montee% - 0.018*pente_descente%)
    (regle empirique, non validee). base est resolue pour tenir l'objectif."""
    kms, k = [], 0
    while k * 1000 < total_m:
        a, b = k * 1000, min((k + 1) * 1000, total_m)
        ia, ib = int(a / STEP_M), min(int(b / STEP_M), len(e) - 1)
        seg = [e[j + 1] - e[j] for j in range(ia, ib)]
        up = sum(x for x in seg if x > 0)
        dn = -sum(x for x in seg if x < 0)
        L = b - a
        f = 1 + 3.3 * up / L - 1.8 * dn / L
        kms.append(
            {
                "km": k + 1,
                "longueur_m": round(L),
                "d_plus": round(up, 1),
                "d_moins": round(dn, 1),
                "f": f,
            }
        )
        k += 1
    base = objectif_s / sum(x["f"] * x["longueur_m"] / 1000 for x in kms)
    for x in kms:
        x["allure_s_km"] = round(base * x["f"])
        x.pop("f")
    return round(base), kms


def osrm(a, b, profile="car"):
    url = (
        f"https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/"
        f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    )
    r = httpx.get(
        url,
        params={"overview": "full", "geometries": "geojson"},
        headers=UA,
        timeout=30,
    )
    r.raise_for_status()
    rt = r.json()["routes"][0]
    return {
        "coords": [
            [round(x, 5), round(y, 5)] for x, y in rt["geometry"]["coordinates"]
        ],
        "km": round(rt["distance"] / 1000, 1),
        "min": round(rt["duration"] / 60),
    }


def parse_hms(s):
    p = [int(x) for x in s.split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def ravitos_from(points, d_pts, ravitos_h):
    out = []
    for p in points:
        txt = f"{p['nom']} {p.get('desc', '')}"
        if re.search(
            r"water|ravit|abastec|agua|água|fruit|gel|powerade|drink",
            txt,
            re.IGNORECASE,
        ):
            i = min(
                range(len(d_pts)), key=lambda j: hav((p["lon"], p["lat"]), d_pts[j][:2])
            )
            out.append(
                {
                    "km": round(d_pts[i][2] / 1000, 2),
                    "libelle": (p.get("desc") or p["nom"])[:80],
                    "borne": p["nom"],
                    "source": "trace",
                    "lon": p["lon"],
                    "lat": p["lat"],
                }
            )
    if out:
        return out
    if ravitos_h:
        src = "agent H"
        rav = [
            {"km": r.get("km"), "libelle": r.get("libelle", ""), "source": src}
            for r in ravitos_h
        ]
        if any(r["km"] is not None for r in rav):
            return rav
    return [
        {
            "km": k,
            "libelle": "Ravitaillement (règlement : tous les 5 km, position estimée)",
            "source": "reglement",
        }
        for k in RAVITOS_REGLEMENT
    ]


def locate(km, pts):
    if km is None:
        return None
    i = min(len(pts) - 1, int(km * 1000 / STEP_M))
    return pts[i][0], pts[i][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?")
    ap.add_argument("--objectif", default="1:45:00")
    ap.add_argument("--fallback", action="store_true")
    ap.add_argument("--h-run", help="json du run H (ravitos, provenance)")
    ap.add_argument(
        "--comparer-openmeteo", action="store_true", help="2e MNT (Copernicus 90 m)"
    )
    ap.add_argument("--ville", default="lisbonne", choices=list(WEEKENDS))
    ap.add_argument("--out", default=str(DATA / "course.json"))
    a = ap.parse_args()
    t0 = time.time()
    h = json.loads(Path(a.h_run).read_text()) if a.h_run else {}
    ans = h.get("answer") or {}
    if isinstance(ans, str):
        try:
            ans = json.loads(ans)
        except ValueError:
            ans = {}
    out = {
        "weekend": WEEKENDS[a.ville],
        "objectif": a.objectif,
        "provenance": {
            "h_session": h.get("session_id"),
            "carte": ans.get("url_carte"),
            "edition_carte": ans.get("edition_carte"),
        },
    }
    timings = {}
    if a.fallback or not a.trace:
        dep, arr = FALLBACK_POINTS["depart"], FALLBACK_POINTS["arrivee"]
        out["mode"] = "fallback"
        out["depart"], out["arrivee"] = dep, arr
        out["course"] = None
    else:
        name, line, points = parse_trace(a.trace)
        pts, total = resample(line)
        stem = re.sub(r"\W+", "_", Path(a.trace).stem)
        ele_raw, dt, ntiles = elevations_terrarium(
            pts, DATA / f"ele_mapterhorn_{stem}.json"
        )
        timings["altitude_mapterhorn_s"] = round(dt, 2)
        timings["tuiles_mnt"] = ntiles
        ele_om = None
        if a.comparer_openmeteo:
            ele_om, dt2 = elevations(pts, DATA / f"ele_openmeteo_{stem}.json")
            timings["altitude_openmeteo_s"] = round(dt2, 2)
        ele_fix, fixes = correct_jumps(ele_raw)
        ele_s = smooth(ele_fix)
        d = [p[2] for p in pts]
        base, kms = pace_plan(d, ele_s, total, parse_hms(a.objectif))
        rav = ravitos_from(points, pts, ans.get("ravitos"))
        for r in rav:
            if "lon" not in r and (ll := locate(r["km"], pts)):
                r["lon"], r["lat"] = ll
        bornes = []
        for p in points:
            m = re.match(r"\s*KM\s*(\d+)", p["nom"], re.IGNORECASE)
            if m:
                bornes.append(
                    {
                        "km": int(m.group(1)),
                        "lon": p["lon"],
                        "lat": p["lat"],
                        "source": "trace",
                    }
                )
        if not bornes:
            bornes = [
                {
                    "km": k,
                    "lon": locate(k, pts)[0],
                    "lat": locate(k, pts)[1],
                    "source": "calcul",
                }
                for k in range(1, int(total / 1000) + 1)
            ]
        out["mode"] = "trace"
        out["depart"] = {"nom": "Départ", "lon": pts[0][0], "lat": pts[0][1]}
        out["arrivee"] = {"nom": "Arrivée", "lon": pts[-1][0], "lat": pts[-1][1]}
        out["course"] = {
            "nom_trace": name,
            "fichier": Path(a.trace).name,
            "distance_km": round(total / 1000, 2),
            "points_source": len(line),
            "pas_m": STEP_M,
            "coords": [[round(p[0], 6), round(p[1], 6)] for p in pts],
            "d_m": [round(x) for x in d],
            "ele_brut": [round(x, 1) for x in ele_raw],
            "ele": [round(x, 1) for x in ele_s],
            "corrections": [
                {
                    **f,
                    "km0": round(d[f["i0"]] / 1000, 2),
                    "km1": round(d[f["i1"]] / 1000, 2),
                }
                for f in fixes
            ],
            "d_plus": {
                "brut": gain(ele_raw)[0],
                "brut_lisse": gain(smooth(ele_raw))[0],
                "corrige_lisse": gain(ele_s)[0],
                "d_moins_corrige": gain(ele_s)[1],
            },
            "d_plus_openmeteo": (
                {
                    "brut": gain(ele_om)[0],
                    "corrige_lisse": gain(smooth(correct_jumps(ele_om)[0]))[0],
                }
                if ele_om
                else None
            ),
            "alt_min": round(min(ele_s)),
            "alt_max": round(max(ele_s)),
            "cotes": climbs(d, ele_s),
            "ravitos": rav,
            "bornes": sorted(bornes, key=lambda b: b["km"]),
            "allure_base_s_km": base,
            "allure_km": kms,
        }
    t1 = time.time()
    W = WEEKENDS[a.ville]
    out["trajets"] = {}
    for k, (x, y) in {
        "gare_hotel": (W["gare"], W["hotel"]),
        "hotel_retrait": (W["hotel"], W["retrait"]),
        "hotel_depart": (W["hotel"], out["depart"]),
    }.items():
        try:
            out["trajets"][k] = osrm(x, y)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            out["trajets"][k] = {
                "coords": [[x["lon"], x["lat"]], [y["lon"], y["lat"]]],
                "erreur": str(e)[:80],
            }
    timings["osrm_s"] = round(time.time() - t1, 2)
    timings["total_s"] = round(time.time() - t0, 2)
    out["timings"] = timings
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False))
    c = out["course"]
    print(
        json.dumps(
            {
                "mode": out["mode"],
                "timings": timings,
                **(
                    {
                        k: c[k]
                        for k in (
                            "distance_km",
                            "points_source",
                            "d_plus",
                            "d_plus_openmeteo",
                            "alt_min",
                            "alt_max",
                            "corrections",
                            "cotes",
                            "ravitos",
                            "allure_base_s_km",
                        )
                    }
                    if c
                    else {}
                ),
                "trajets": {
                    k: {kk: v.get(kk) for kk in ("km", "min", "erreur")}
                    for k, v in out["trajets"].items()
                },
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
