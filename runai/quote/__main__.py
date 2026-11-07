"""Relevé ponctuel : python -m runai.quote <url|slug> [épreuve] [--option NOM]... [--hotel EUR] [--transport EUR]"""

import argparse
import json
import time

from runai.quote import fetch_quote, weekend_cost


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m runai.quote")
    ap.add_argument("url")
    ap.add_argument("epreuve", nargs="?")
    ap.add_argument("--option", action="append", default=[])
    ap.add_argument("--hotel", type=float)
    ap.add_argument("--transport", type=float)
    a = ap.parse_args()
    t0 = time.perf_counter()
    devis = fetch_quote(a.url, a.epreuve)
    duree = round(time.perf_counter() - t0, 2)
    cout = weekend_cost(devis, a.option, a.hotel, a.transport)
    print(
        json.dumps(
            {
                "duree_s": duree,
                "devis": devis.model_dump(mode="json"),
                "cout": cout.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
