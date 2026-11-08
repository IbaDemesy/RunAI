"""Report mission duration and H usage from saved JSONL traces."""

import argparse
import json
from pathlib import Path

from runai.metrics import MissionMetrics, compute
from runai.redaction import redact_secrets
from runai.tracing import TraceWriter, iter_traces


def table(headers: list[str], rows: list[list[str]], markdown: bool) -> str:
    def safe(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    cells = [[safe(value) for value in row] for row in [headers, *rows]]
    if markdown:
        cells.insert(1, ["---"] * len(headers))
        return "\n".join("| " + " | ".join(row) + " |" for row in cells)
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    return "\n".join("  ".join(value.ljust(width) for value, width in zip(row, widths)) for row in cells)


def render(reports: list[MissionMetrics], all_missions: bool, markdown: bool) -> str:
    if all_missions:
        headers = ["Mission", "Status", "Duration (s)", "H steps", "Cost (USD)", "Agents"]
        rows = [[r.mission_id, r.status, f"{r.wall_s:.3f}", str(r.totals.h_steps),
                 f"{r.totals.h_cost_usd:.6f}", str(r.totals.agents)] for r in reports]
    else:
        headers = ["Agent", "Status", "Stop point", "Duration (s)", "H steps", "Cost (USD)", "Hosts"]
        rows = [[kind, step.status, step.stop_point or "-", f"{step.duration_s:.3f}",
                 str(step.h_steps) if step.h_steps is not None else "-",
                 f"{step.total_cost_usd:.6f}" if step.total_cost_usd is not None else "-",
                 ", ".join(step.unique_hosts) or "-"] for kind, step in reports[0].steps.items()]
    return table(headers, rows, markdown)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Mission JSONL file or trace directory")
    parser.add_argument("--all", action="store_true", help="Report all missions in a directory")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Print JSON")
    output.add_argument("--md", action="store_true", help="Print a Markdown table")
    args = parser.parse_args()
    if not args.path.exists():
        parser.error("Trace path does not exist")
    if args.all != args.path.is_dir():
        parser.error("Use --all with a directory, or provide a JSONL file")
    try:
        traces = iter_traces(args.path) if args.all else [
            (args.path.stem, TraceWriter(args.path.stem, args.path.parent).read())
        ]
        reports = [compute(mid, events) for mid, events in traces]
    except (ValueError, OSError) as error:
        parser.error(redact_secrets(f"Cannot read trace: {error}"))
    if args.json:
        data = [report.model_dump(mode="json") for report in reports]
        print(json.dumps(data if args.all else data[0], indent=2))
    else:
        print(render(reports, args.all, args.md))


if __name__ == "__main__":
    main()
