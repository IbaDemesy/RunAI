"""Lance l'extraction Linkup sur les courses de test et sauvegarde résultats, métriques, timeline et .ics."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from extract import extract_race, extract_race_fetch, find_open_races
from linkup import LinkupClient
from timeline import build_timeline, to_ics

RACES = [
    "Wizz Air Milano Marathon 2027",
    "Semi-marathon de La Rochelle 2027",
    "Marathon Royan U Côte de Beauté 2027",
    "EDP Meia Maratona de Lisboa 2027",
    "Schneider Electric Marathon de Paris 2027",
]
OUT = Path(__file__).parent / "results"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


def main(names: list[str]) -> None:
    mode = "fetch" if "--fetch" in sys.argv else "deep"
    out = OUT if mode == "deep" else OUT / "fetch"
    out.mkdir(parents=True, exist_ok=True)
    client = LinkupClient()
    summary = []
    for name in names:
        if (out / f"{slug(name)}.json").exists() and "--force" not in sys.argv:
            summary.append(json.loads((out / f"{slug(name)}.json").read_text()) | {"race": None})
            continue
        race, calls = (extract_race_fetch if mode == "fetch" else extract_race)(name, client)
        try:
            steps = build_timeline(race)
        except ValueError as e:
            steps = []
            print(f"[{name}] timeline impossible : {e}")
        rec = {"query": name, "race": race.model_dump(), "calls": [c.__dict__ for c in calls],
               "timeline": [s.as_dict() for s in steps]}
        (out / f"{slug(name)}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        if steps:
            (out / f"{slug(name)}.ics").write_text(to_ics(steps, race.name))
        summary.append({"query": name, "calls": rec["calls"], "status": race.registration_status,
                        "platform": race.registration_platform})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if mode == "fetch":
        return
    open_races, m = find_open_races(client)
    (OUT / "open_races.json").write_text(json.dumps({"races": open_races.model_dump()["races"], "call": m.__dict__},
                                                    ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("--")] or RACES)
