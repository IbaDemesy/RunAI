"""Extract H session history without contacting any partner API.

Usage: python -m scripts.h_runs --traces traces --out h-runs.jsonl --md
The output is replaced on each invocation; --md prints a platform summary.
Unknown values stay null (platform uses 'unknown'). Malformed lines are skipped.
Only explicitly identified sessions are emitted. Duration spans their dated
events; recorded_at is the last event timestamp, making exports reproducible.
Mode is read from provenance, never inferred from a successful result.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.parse import urlsplit

from runai.redaction import redact_secrets


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _date(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    except (AttributeError, TypeError, ValueError):
        return None


def _hostname(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        return url.hostname if url.scheme in ("http", "https") else None
    except ValueError:
        return None


def extract_runs(traces: Path) -> list[dict[str, Any]]:
    """Read JSONL files in a directory, grouping by mission and session ID."""
    records = []
    for path in sorted(traces.glob("*.jsonl")):
        sessions: dict[str, dict] = {}
        dates: dict[str, list[datetime]] = defaultdict(list)
        latest_step: dict[str, str] = {}
        replays: dict[str, str] = {}
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = _dict(json.loads(line))
                except (ValueError, RecursionError):
                    continue
                data = _dict(event.get("data"))
                result = _dict(data.get("result"))
                details = _dict(result.get("data"))
                raw = _dict(_dict(data.get("event")).get("data"))
                step = _text(data.get("step")) or _text(result.get("kind"))
                session = (_text(data.get("h_session_id")) or _text(data.get("session_id"))
                           or _text(result.get("h_session_id")))
                if not session and event.get("type") == "step_done" and step:
                    session = latest_step.get(step)
                if not session:
                    continue
                if step:
                    latest_step[step] = session
                record = sessions.setdefault(session, dict.fromkeys([
                    "step_kind", "status", "outcome", "stop_point", "steps", "duration_s",
                    "total_cost", "error_code", "recorded_at", "mode",
                ]) | {"schema_version": "h-runs.v1", "mission_id": path.stem,
                      "session_id": session, "platform": "unknown"})
                if step:
                    record["step_kind"] = step
                at = _date(event.get("at"))
                if at:
                    dates[session].append(at)
                original = _text(details.get("replay_of"))
                if original and original != session:
                    replays[original] = session
                if data.get("mode") == "replay":
                    record["mode"] = "replay"
                metrics = _dict(raw.get("metrics"))
                for source in (raw, metrics, data, details, result):
                    for key in ("status", "outcome", "stop_point", "error_code"):
                        if _text(source.get(key)):
                            record[key] = source[key]
                    for key in ("steps", "total_cost"):
                        if _number(source.get(key)) is not None:
                            record[key] = source[key]
                    mode = _dict(source.get("provenance")).get("mode")
                    if mode in ("live", "demo", "replay"):
                        record["mode"] = mode
                if not record["status"]:
                    record["status"] = _text(details.get("h_status")) or _text(data.get("h_status"))
                # Prefer final URLs to the initial platform when navigation crosses hosts.
                urls = (data.get("start_url"), _dict(raw.get("metadata")).get("url"),
                        data.get("url"), data.get("last_url"), details.get("last_url"), result.get("url"))
                for url in urls:
                    if host := _hostname(url):
                        record["platform"] = host
                if record["error_code"] is None:
                    h_status = details.get("h_status") or data.get("h_status")
                    if h_status in ("timed_out", "interrupted"):
                        record["error_code"] = h_status
        # Replayed events keep the original H session id; fold them into the replay run.
        for original, replay in replays.items():
            if original in sessions and replay in sessions:
                old = sessions.pop(original)
                new = sessions[replay]
                for key, value in old.items():
                    if new.get(key) in (None, "unknown"):
                        new[key] = value
                new["session_id"] = replay
                dates[replay] += dates.pop(original, [])
        for session, record in sessions.items():
            if timestamps := dates[session]:
                record["duration_s"] = (max(timestamps) - min(timestamps)).total_seconds()
                record["recorded_at"] = max(timestamps).isoformat()
            records.append(record)
    return records


def markdown_summary(records: list[dict[str, Any]]) -> str:
    """Summarize all runs, excluding null measurements from aggregates."""
    groups = defaultdict(list)
    for record in records:
        groups[record["platform"]].append(record)
    lines = ["| Platform | Runs | Success rate | Median steps | Median duration (s) | Mean cost |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for platform, runs in sorted(groups.items()):
        values = []
        for key, aggregate in (("steps", median), ("duration_s", median), ("total_cost", mean)):
            numbers = [r[key] for r in runs if _number(r.get(key)) is not None]
            values.append(f"{aggregate(numbers):.3f}" if numbers else "—")
        rate = sum(r["status"] == "stopped_before_commitment" for r in runs) / len(runs)
        safe_platform = platform.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {safe_platform} | {len(runs)} | {rate:.1%} | {' | '.join(values)} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--md", action="store_true", help="Print a Markdown platform summary")
    args = parser.parse_args()
    if not args.traces.is_dir():
        parser.error("--traces must be an existing directory")
    records = redact_secrets(extract_runs(args.traces))
    with args.out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    if args.md:
        print(redact_secrets(markdown_summary(records)))
