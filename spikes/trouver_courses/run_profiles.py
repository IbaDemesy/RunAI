"""Lance les 4 profils, enregistre results/<id>.json et results/summary.json."""

import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from finder import Finder
from profiles import PROFILES

load_dotenv()
OUT = Path(__file__).parent / "results"


def balance() -> float | None:
    try:
        r = httpx.get(
            "https://api.linkup.so/v1/credits/balance",
            headers={"Authorization": f"Bearer {os.environ['LINKUP_API_KEY']}"},
            timeout=10,
        )
        return r.json().get("balance")
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def main() -> None:
    OUT.mkdir(exist_ok=True)
    summary = []
    for p in PROFILES:
        b0 = balance()
        t = time.time()
        res = Finder().run(p)
        dt = round(time.time() - t, 2)
        b1 = balance()
        res["linkup_balance_delta_usd"] = (
            round(b0 - b1, 4) if b0 is not None and b1 is not None else None
        )
        (OUT / f"{p.id}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2, default=str)
        )
        row = {
            "profile": p.id,
            "wall_s": dt,
            "n_candidates": res["n_candidates"],
            "n_open": len(res["recommended_open"]),
            "n_to_check_H": len(res["to_check_with_H"]),
            "n_not_open": len(res["not_open"]),
            "metrics": res["metrics"],
            "linkup_balance_delta_usd": res["linkup_balance_delta_usd"],
            "open": [
                (r["name"], r["date"], r["registration_url"])
                for r in res["recommended_open"]
            ],
        }
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
