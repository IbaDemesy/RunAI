"""Export a mission snapshot and its events as a redacted replay.v1 trace."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx


def record(args: argparse.Namespace) -> None:
    # Support both `python scripts/record_replay.py` and module invocation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from runai.app.replay import ReplayTrace
    from runai.config import get_settings
    from runai.models import Race
    from runai.tracing import TraceWriter

    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    else:
        url = f"{args.base_url.rstrip('/')}/api/missions/{quote(args.mission, safe='')}"
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        snapshot = response.json()

    mission_id = snapshot.get("id") or snapshot.get("mission_id") or args.mission
    snapshot["id"] = mission_id
    if not snapshot.get("events"):
        if not mission_id:
            raise ValueError("The snapshot has no events or mission ID.")
        directory = args.traces_dir or get_settings().traces_dir
        snapshot["events"] = [
            event.model_dump(mode="json")
            for event in TraceWriter(mission_id, traces_dir=directory).read()
        ]
        if not snapshot["events"]:
            raise ValueError(
                "No recorded events found. Run beside the server's traces directory "
                "or pass --traces-dir with a copy of its JSONL traces."
            )

    snapshot["questions"] = [
        {
            "kind": question.get("kind", question.get("step")),
            "question": question.get("question", question.get("text")),
            "options": question.get("options", question.get("choices", [])),
        }
        for question in snapshot.get("questions", [])
    ]
    trace = ReplayTrace.from_mission_snapshot(snapshot, label=args.label)
    trace.transcript = args.transcript if args.transcript is not None else snapshot.get("transcript")
    if args.race_json:
        trace.race = Race.model_validate_json(args.race_json.read_text(encoding="utf-8"))
    trace.dump(args.output)
    print(f"Recorded {len(trace.steps)} steps to {args.output} ({trace.recorded_mode.value}).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mission", help="Mission ID to fetch from the running server.")
    source.add_argument("--snapshot", type=Path, help="Read a saved mission snapshot JSON file instead.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Running server URL.")
    parser.add_argument("--traces-dir", type=Path, help="Server JSONL directory (default: RUNAI_TRACES_DIR or repo traces/).")
    parser.add_argument("--output", type=Path, required=True, help="Destination replay.v1 JSON file.")
    parser.add_argument("--label", help="Override the replay's display label.")
    parser.add_argument("--transcript", help="Override the recorded voice transcript.")
    parser.add_argument("--race-json", type=Path, help="Override race details with a Race JSON file.")
    args = parser.parse_args(argv)
    try:
        record(args)
    except (OSError, ValueError, httpx.HTTPError) as error:
        parser.exit(1, f"Could not record replay ({type(error).__name__}). Check the input, server, and trace paths.\n")


if __name__ == "__main__":
    main()
