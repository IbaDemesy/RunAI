"""Repeatable slot extraction evaluation; live calls are opt-in only."""

import argparse
import asyncio
import json
import math
import os
import subprocess
import time
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path

from runai.framing.interpret import extract_slots

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/framing_evals.jsonl"
TODAY = date(2026, 11, 7)
SLOTS = ("city", "origin", "race", "edition", "race_date", "date_window",
         "distance_km", "budget", "nights", "transport_mode")


def load_cases(path=FIXTURES):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def equal(left, right):
    if isinstance(left, str) and isinstance(right, str):
        def normalize(value):
            return "".join(c for c in unicodedata.normalize("NFKD", value.casefold().strip())
                           if not unicodedata.combining(c))
        return normalize(left) == normalize(right)
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, abs_tol=0.01, rel_tol=0)
    return left is None and right is None


def score(cases, predict):
    """Score a synchronous predictor without IO, mutation, or history writes."""
    per_slot = {slot: {"tp": 0, "fp": 0, "fn": 0} for slot in SLOTS}
    results = []
    for case in cases:
        expected, predicted = case["expected"], predict(case["text"])
        wrong = missing = 0
        for slot in expected.keys() | predicted.keys():
            counts = per_slot.setdefault(slot, {"tp": 0, "fp": 0, "fn": 0})
            match = slot in expected and slot in predicted and equal(expected[slot], predicted[slot])
            counts["tp"] += int(match)
            counts["fp"] += int(slot in predicted and not match)
            counts["fn"] += int(slot in expected and not match)
            wrong += int(slot in predicted and not match)
            missing += int(slot in expected and slot not in predicted)
        results.append({"id": case["id"], "tags": case["tags"], "exact": not wrong and not missing,
                        "wrong_fills": wrong, "missing": missing,
                        "expected": expected, "predicted": predicted})
    for counts in per_slot.values():
        counts["precision"] = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
        counts["recall"] = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0

    def summary(rows):
        return {"n_cases": len(rows),
                "exact_match": sum(r["exact"] for r in rows) / len(rows) if rows else 0.0,
                "wrong_fills": sum(r["wrong_fills"] for r in rows),
                "missing": sum(r["missing"] for r in rows)}

    safe = summary([r for r in results if "must_not_misfill" in r["tags"]])
    return {**summary(results), "per_slot": per_slot, "must_not_misfill": safe,
            "must_not_misfill_wrong_fills": safe["wrong_fills"],
            "non_pending_u1": summary([r for r in results if "pending_u1" not in r["tags"]]),
            "failures": [r for r in results if not r["exact"]]}


async def live_predictions(cases):
    import httpx

    from runai.framing.holo import HoloPhraser

    class CheckedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            try:
                async with httpx.AsyncHTTPTransport() as transport:
                    response = await transport.handle_async_request(request)
                    await response.aread()
            except httpx.HTTPError as error:
                raise RuntimeError("Live API transport failed; no history written") from error
            if response.status_code >= 400:
                await response.aclose()
                raise RuntimeError(f"Live API returned HTTP {response.status_code}; no history written")
            return response

    phraser = HoloPhraser(os.environ["HAI_API_KEY"], model="holo4-35b-a3b",
                         transport=CheckedTransport(), timeout_s=30)
    semaphore = asyncio.Semaphore(4)

    async def extract(case):
        async with semaphore:
            return case["text"], await phraser.extract(case["text"], {})

    return dict(await asyncio.gather(*(extract(case) for case in cases))), phraser.model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args()
    if args.live and os.environ.get("CI"):
        parser.error("Live evaluation is forbidden in CI")
    if args.live and not os.environ.get("HAI_API_KEY"):
        parser.error("--live requires HAI_API_KEY")
    started = time.perf_counter()
    cases = load_cases(args.fixtures)
    model = None
    if args.live:
        from runai.framing.holo import EXTRACTABLE

        try:
            predictions, model = asyncio.run(live_predictions(cases))
        except RuntimeError as error:
            parser.exit(1, f"{error}\n")
        cases = [{**c, "expected": {k: v for k, v in c["expected"].items() if k in EXTRACTABLE}} for c in cases]
        result = score(cases, lambda text: {k: v for k, v in predictions[text].items() if k in EXTRACTABLE})
    else:
        result = score(cases, lambda text: extract_slots(text, today=TODAY))
    duration = round(time.perf_counter() - started, 3)
    print(f"{'live' if args.live else 'offline'}: {result['n_cases']} cases, {duration:.3f}s")
    print(f"{'subset':24} {'exact':>8} {'wrong':>7} {'missing':>8}")
    for label, values in (("all", result), ("must_not_misfill", result["must_not_misfill"]),
                          ("non_pending_u1", result["non_pending_u1"])):
        print(f"{label:24} {values['exact_match']:8.1%} {values['wrong_fills']:7} {values['missing']:8}")
    print(f"{'slot':18} {'TP':>4} {'FP':>4} {'FN':>4} {'precision':>10} {'recall':>8}")
    for slot, counts in result["per_slot"].items():
        print(f"{slot:18} {counts['tp']:4} {counts['fp']:4} {counts['fn']:4} {counts['precision']:10.1%} {counts['recall']:8.1%}")
    print("Failing cases: " + (", ".join(r["id"] for r in result["failures"]) or "none"))
    for failure in result["failures"]:
        print(f"  {failure['id']}: expected={failure['expected']} predicted={failure['predicted']}")
    if not args.no_history:
        try:
            sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            sha = "unknown"
        record = {key: result[key] for key in ("n_cases", "exact_match", "wrong_fills", "missing", "per_slot", "must_not_misfill_wrong_fills")}
        record.update(date=datetime.now(UTC).isoformat(), git_sha=sha,
                      mode="live" if args.live else "offline", duration_s=duration)
        if model:
            record["model"] = model
        history = ROOT / "docs/evals/framing_history.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
