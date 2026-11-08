"""Sequential quality gate with JSON, JUnit and TAP adapters.

JUnit does not distinguish non-strict XPASS from an ordinary pass. Strict
XPASS is counted as both xpassed and failed. TAP counts top-level tests only;
nested assertions contribute to their parent's result, not separate counts.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from scripts.test_history.schema import (
    CI,
    Failure,
    Git,
    RunRecord,
    Suite,
    Suites,
    TestResult,
)

ROOT = Path(__file__).resolve().parents[2]
NODE_PATTERNS = (
    "web/flyover/tests/*.test.js",
    "tests/contracts/*.test.js",
    "runai/app/static/tests/*.test.js",
    "web/voice/tests/*.test.js",
)


def parse_ruff(output: str) -> Suite:
    items = json.loads(output)
    if not isinstance(items, list):
        raise TypeError("Expected a ruff JSON array")
    suite = Suite(verdict="fail" if items else "pass")
    for item in items:
        location = item["location"]
        suite.failures.append(Failure(
            id=f'{item["filename"]}:{location["row"]}:{location["column"]}:{item["code"]}',
            message=item["message"],
        ))
    suite.counts.failed = len(items)
    return suite


def parse_junit(output: str) -> Suite:
    root = ET.fromstring(output)
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("Expected JUnit testsuites or testsuite")
    suite = Suite(verdict="pass")
    for case in root.iter("testcase"):
        test_id = f'{case.get("classname", "")}::{case.attrib["name"]}'
        outcome = "passed"
        for tag, result in (("error", "error"), ("failure", "failed"), ("skipped", "skipped")):
            detail = case.find(tag)
            if detail is None:
                continue
            message = detail.get("message") or detail.text or tag
            outcome = result
            if tag == "skipped" and "pytest.xfail" in (
                detail.get("type", "") + message
            ):
                outcome = "xfailed"
            if tag in {"failure", "error"}:
                suite.failures.append(Failure(id=test_id, message=message))
                if "[XPASS(strict)]" in message:
                    suite.counts.xpassed += 1
            break
        field = "errors" if outcome == "error" else outcome
        setattr(suite.counts, field, getattr(suite.counts, field) + 1)
        suite.tests.append(TestResult(
            id=test_id, outcome=outcome, duration_s=float(case.get("time", "0")),
        ))
    # Collection errors are emitted outside testcase by some JUnit producers.
    for error in root.findall("./testsuite/error") + root.findall("./error"):
        suite.counts.errors += 1
        suite.failures.append(Failure(id="collection", message=error.text or "Collection error"))
    if suite.counts.failed or suite.counts.errors:
        suite.verdict = "fail"
    return suite


def parse_tap(output: str) -> Suite:
    suite = Suite(verdict="pass")
    current = None
    plan = None
    for line in output.splitlines():
        match = re.match(r"^(not ok|ok)\s+(\d+)(?:\s+-)?\s*(.*)$", line)
        if match:
            status, number, description = match.groups()
            directive = re.search(r"\s+#\s*(SKIP|TODO)\b", description, re.IGNORECASE)
            outcome = "passed" if status == "ok" else "failed"
            if directive:
                if directive[1].upper() == "SKIP":
                    outcome = "skipped"
                else:
                    outcome = "xpassed" if status == "ok" else "xfailed"
            current = TestResult(id=f"{number}::{description}", outcome=outcome)
            suite.tests.append(current)
            setattr(suite.counts, outcome, getattr(suite.counts, outcome) + 1)
            if outcome == "failed":
                suite.failures.append(Failure(id=current.id, message=description))
        elif current and (duration := re.match(r"^  duration_ms:\s*([\d.]+)", line)):
            current.duration_s = float(duration[1]) / 1000
        elif match := re.match(r"^1\.\.(\d+)", line):
            plan = int(match[1])
    if plan is None or plan != len(suite.tests):
        raise ValueError("Missing or inconsistent top-level TAP plan")
    if suite.counts.failed:
        suite.verdict = "fail"
    return suite


def run_suite(name: str) -> Suite:
    if name == "node" and not shutil.which("node"):
        return Suite(verdict="skip", reason="node is not on PATH")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="runai-check-") as directory:
            junit = Path(directory) / "junit.xml"
            if name == "ruff":
                candidates = [Path(sys.executable).parent / "ruff", ROOT / ".venv/bin/ruff"]
                executable = next((str(p) for p in candidates if p.is_file()), "ruff")
                command = [executable, "check", ".", "--output-format", "json"]
                parser = parse_ruff
            elif name == "pytest":
                command = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}"]
                parser = parse_junit
            else:
                files = [path for pattern in NODE_PATTERNS for path in sorted(glob.glob(pattern, root_dir=ROOT))]
                command = ["node", "--test", "--test-reporter=tap", *files]
                parser = parse_tap
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            output = junit.read_text() if name == "pytest" else result.stdout
            suite = parser(output)
            if result.returncode and suite.verdict != "fail":
                suite = Suite(verdict="error", reason=(result.stderr or result.stdout or f"Exit {result.returncode}").strip())
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        suite = Suite(verdict="error", reason=str(exc))
    suite.duration_s = time.monotonic() - started
    return suite


def git_info() -> Git:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    return Git(sha=git("rev-parse", "HEAD"), branch=git("rev-parse", "--abbrev-ref", "HEAD"),
               dirty=bool(git("status", "--porcelain")))


def ci_info() -> CI | None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    run_id = os.environ.get("GITHUB_RUN_ID")
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    url = f"{server}/{repository}/actions/runs/{run_id}" if all((server, repository, run_id)) else None
    return CI(provider="github", run_id=run_id, run_url=url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".test-history"))
    parser.add_argument("--wave", default=os.environ.get("RUNAI_WAVE"))
    parser.add_argument("--skip", action="append", choices=("ruff", "pytest", "node"), default=[])
    args = parser.parse_args(argv)
    started = datetime.now(UTC)
    clock = time.monotonic()
    git = git_info()
    suites = Suites(**{
        name: Suite(verdict="skip", reason="Skipped by flag") if name in args.skip else run_suite(name)
        for name in ("ruff", "pytest", "node")
    })
    verdict = "fail" if any(s.verdict in {"fail", "error"} for s in (suites.ruff, suites.pytest, suites.node)) else "pass"
    run_id = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{git.sha[:7]}"
    record = RunRecord(
        run_id=run_id, started_at=started.isoformat(),
        finished_at=datetime.now(UTC).isoformat(), duration_s=time.monotonic() - clock,
        git=git, wave=args.wave, ci=ci_info(), verdict=verdict, suites=suites,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    suffix = 0
    while True:
        record.run_id = run_id if suffix == 0 else f"{run_id}-{suffix}"
        path = args.out / f"{record.run_id}.json"
        try:
            with path.open("x") as stream:
                stream.write(record.model_dump_json(indent=2) + "\n")
            break
        except FileExistsError:
            suffix += 1
    print(f"{verdict.upper()} in {record.duration_s:.2f}s")
    for name in ("ruff", "pytest", "node"):
        suite = getattr(suites, name)
        counts = suite.counts
        print(f"{name}: {suite.verdict} ({counts.passed} passed, {counts.failed} failed, "
              f"{counts.skipped} skipped, {counts.xfailed} xfailed, {counts.xpassed} xpassed, "
              f"{counts.errors} errors)" + (f" - {suite.reason}" if suite.reason else ""))
    print(f"Record: {path}")
    return int(verdict == "fail")
