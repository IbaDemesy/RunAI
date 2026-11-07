import argparse
import json

from runai.search import locate_race, search_race


def main() -> None:
    parser = argparse.ArgumentParser(description="Sourced race details via Linkup (live call, ~$0.055 in deep mode)")
    parser.add_argument("request", help="Free-text request, e.g. 'Lisbon half marathon 2027'")
    parser.add_argument("--depth", choices=["standard", "deep"], default="deep")
    parser.add_argument("--no-geo", action="store_true", help="Do not geocode the start or bib pick-up")
    args = parser.parse_args()

    sheet = search_race(args.request, depth=args.depth)
    output = {"sheet": sheet.model_dump(mode="json"), "reliable": sheet.is_reliable}
    if not args.no_geo:
        output["locations"] = locate_race(sheet).model_dump(mode="json")
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
