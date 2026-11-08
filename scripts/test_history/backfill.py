"""Recover approximate CI history and provide publication fallbacks."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from glob import glob
from pathlib import Path

STEP_SUITES = {
    "Lint": "ruff",
    "Test": "pytest",
    "JavaScript syntax": "node",
    "JavaScript tests": "node",
}


def runner(args):
    return json.loads(subprocess.check_output(args, text=True))


def verdict(conclusion):
    return {"success": "pass", "failure": "fail", "skipped": "skip",
            "cancelled": "skip", "timed_out": "fail"}.get(conclusion, "error")


def duration(start, end):
    if not start or not end:
        return None
    return max(0, (datetime.fromisoformat(end)
                   - datetime.fromisoformat(start)).total_seconds())


def suite(result, seconds=None):
    return {"verdict": result, "duration_s": seconds, "counts": None,
            "failures": [], "tests": []}


def record(run, suites, source, branch="main"):
    return {
        "schema_version": "test-history.v1", "run_id": str(run["databaseId"]),
        "started_at": run["createdAt"], "finished_at": run["updatedAt"],
        "duration_s": duration(run["createdAt"], run["updatedAt"]),
        "git": {"sha": run["headSha"], "branch": branch, "dirty": False},
        "wave": None, "ci": {"provider": "github-actions",
                              "run_id": str(run["databaseId"]), "run_url": run["url"]},
        "verdict": verdict(run["conclusion"]), "suites": suites, "source": source,
    }


def backfill(limit=30, runner=runner):
    runs = runner(["gh", "run", "list", "--workflow", "CI", "--branch", "main",
                   "--limit", str(limit), "--json",
                   "databaseId,headSha,status,conclusion,createdAt,updatedAt,url"])
    records = []
    for run in runs:
        if run["status"] != "completed":
            continue
        jobs = runner(["gh", "run", "view", str(run["databaseId"]), "--json", "jobs"])
        suites = {}
        for job in jobs["jobs"]:
            for step in job["steps"]:
                name = STEP_SUITES.get(step["name"])
                if name is None:
                    continue
                result = verdict(step["conclusion"])
                seconds = duration(step["startedAt"], step["completedAt"])
                if name in suites:
                    previous = suites[name]
                    result = max((previous["verdict"], result),
                                 key={"skip": 0, "pass": 1, "fail": 2, "error": 3}.get)
                    previous_seconds = previous["duration_s"]
                    seconds = (seconds + previous_seconds
                               if seconds is not None and previous_seconds is not None else None)
                suites[name] = suite(result, seconds)
        records.append(record(run, suites, "backfill"))
    return records


def filename(item):
    stamp = datetime.fromisoformat(item["started_at"]) if item["started_at"] else None
    if stamp is None:
        return f"unknown-{item['git']['sha'][:7]}-gh{item['ci']['run_id']}.json"
    return f"{stamp:%Y%m%dT%H%M%SZ}-{item['git']['sha'][:7]}-gh{item['ci']['run_id']}.json"


def fallback_record():
    start = datetime.now(UTC).isoformat()
    suites = {}
    syntax_files = [path for pattern in (
        "runai/app/static/*.js", "web/flyover/*.js", "web/voice/voice-input.js")
        for path in sorted(glob(pattern)) or [pattern]]
    test_files = [path for pattern in (
        "web/flyover/tests/*.test.js", "tests/contracts/*.test.js",
        "runai/app/static/tests/*.test.js", "web/voice/tests/*.test.js")
        for path in sorted(glob(pattern)) or [pattern]]
    node_commands = [["node", "--check", path] for path in syntax_files]
    node_commands.append(["node", "--test", *test_files])
    for name, commands in (("ruff", [["ruff", "check", "."]]),
                           ("pytest", [[sys.executable, "-m", "pytest", "-q"]]),
                           ("node", node_commands)):
        before = datetime.now(UTC)
        result = "pass"
        try:
            for command in commands:
                if subprocess.run(command, check=False).returncode != 0:
                    result = "fail"
                    break
        except OSError:
            result = "error"
        suites[name] = suite(result, (datetime.now(UTC) - before).total_seconds())
    run_id = os.environ.get("GITHUB_RUN_ID", datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
    run = {"databaseId": run_id, "createdAt": start,
           "updatedAt": datetime.now(UTC).isoformat(),
           "headSha": os.environ.get("GITHUB_SHA", "unknown"),
           "url": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                  f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run_id}",
           "conclusion": "success" if all(s["verdict"] == "pass" for s in suites.values()) else "failure"}
    item = record(run, suites, "fallback", branch=os.environ.get("GITHUB_REF_NAME", "main"))
    item["wave"] = os.environ.get("WAVE") or None
    return item


def main(argv=None, runner=runner):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("history"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fallback-record", action="store_true")
    parser.add_argument("--fallback-summary", action="store_true")
    parser.add_argument("--history", type=Path)
    args = parser.parse_args(argv)
    if args.fallback_summary:
        rows = ["# Test history", "", "| Started | Verdict | Record |", "| --- | --- | --- |"]
        for path in sorted((args.history or args.out / "records").glob("*.json"), reverse=True):
            item = json.loads(path.read_text())
            rows.append(f"| {item['started_at']} | {item['verdict']} | [JSON](records/{path.name}) |")
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.md").write_text("\n".join(rows) + "\n")
        return
    items = [fallback_record()] if args.fallback_record else backfill(args.limit, runner)
    for item in items:
        content = json.dumps(item, indent=2) + "\n"
        if args.dry_run:
            print(content, end="")
        else:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / filename(item)).write_text(content)


if __name__ == "__main__":
    main()
