"""Render test-history.v1 dictionaries without network access or dependencies."""

import argparse
import html
import json
import logging
import math
from itertools import pairwise
from pathlib import Path
from statistics import median
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)


def _number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _valid(record):
    if not isinstance(record, dict) or record.get("schema_version") != "test-history.v1":
        return False
    if record.get("verdict") is not None and not isinstance(record["verdict"], str):
        return False
    for key in ("git", "ci", "suites"):
        if record.get(key) is not None and not isinstance(record[key], dict):
            return False
    for suite in (record.get("suites") or {}).values():
        if not isinstance(suite, dict):
            return False
        if not isinstance(suite.get("counts", {}), dict):
            return False
        for key in ("tests", "failures"):
            items = suite.get(key, [])
            if not isinstance(items, list) or any(not isinstance(t, dict) for t in items):
                return False
    return True


def load_records(history):
    """Read valid JSON records, warning and continuing on malformed files."""
    records = []
    for path in sorted(Path(history).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not _valid(record):
                raise ValueError("invalid test-history.v1 record")
            records.append(record)
        except (OSError, ValueError) as exc:
            logger.warning("Skipping %s: %s", path, exc)
    return sorted(records, key=lambda r: str(r.get("started_at", "")))


def test_outcomes(record):
    """Return test ID to outcome mappings, including failure-only records."""
    result = {}
    for suite in (record.get("suites") or {}).values():
        for failure in suite.get("failures", []):
            if failure.get("id") is not None:
                result[str(failure["id"])] = "failed"
        for test in suite.get("tests", []):
            if test.get("id") is not None:
                result[str(test["id"])] = str(test.get("outcome", "unknown"))
    return result


def compute_regressions(records):
    """Compare each run with the immediately previous run on its branch."""
    previous = {}
    changes = []
    for record in sorted(records, key=lambda r: str(r.get("started_at", ""))):
        branch = str((record.get("git") or {}).get("branch", ""))
        old = previous.get(branch, {})
        current = test_outcomes(record)
        regressions = sorted(t for t, o in current.items()
                             if old.get(t) == "passed" and o in {"failed", "error", "errors"})
        fixes = sorted(t for t, o in current.items()
                       if (old.get(t) in {"failed", "error", "errors"} and o == "passed")
                       or (old.get(t) == "xfailed" and o == "xpassed"))
        changes.append({"run_id": record.get("run_id"), "regressions": regressions, "fixes": fixes})
        previous[branch] = current
    return changes


def compute_flaky(records):
    """Find IDs with at least two outcome transitions in the last ten runs.

    Compare only observations on the same branch; missing tests are ignored.
    """
    observations = {}
    for record in sorted(records, key=lambda r: str(r.get("started_at", "")))[-10:]:
        branch = str((record.get("git") or {}).get("branch", ""))
        for test_id, outcome in test_outcomes(record).items():
            observations.setdefault((branch, test_id), []).append(outcome)
    return sorted({test_id for (_, test_id), outcomes in observations.items()
                   if sum(a != b for a, b in pairwise(outcomes)) >= 2})


def compute_wave_rollups(records):
    groups = {}
    changes = compute_regressions(records)
    ordered = sorted(records, key=lambda r: str(r.get("started_at", "")))
    for record, change in zip(ordered, changes):
        groups.setdefault(str(record.get("wave", "Unknown")), []).append((record, change))
    return [{"wave": wave, "runs": len(items),
             "pass_rate": sum(r.get("verdict") in {"passed", "pass"} for r, _ in items) / len(items),
             "median_duration": median([r.get("duration_s", 0) if _number(r.get("duration_s"))
                                        else 0 for r, _ in items]),
             "regressions": sum(len(c["regressions"]) for _, c in items)}
            for wave, items in groups.items()]


def slowest_tests(record):
    tests = [dict(t, suite=name) for name, suite in (record.get("suites") or {}).items()
             for t in suite.get("tests", []) if _number(t.get("duration_s"))]
    return sorted(tests, key=lambda t: t["duration_s"], reverse=True)[:10]


def sparkline(values):
    """Render a self-contained, fixed-size SVG duration trend."""
    values = [max(0, v) for v in values if _number(v)]
    if not values:
        return "No duration data"
    maximum = max(values) or 1
    points = " ".join(f"{5 + i * 190 / max(1, len(values) - 1):.2f},{45 - v * 40 / maximum:.2f}"
                      for i, v in enumerate(values))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 50" '
            'width="200" height="50" role="img" aria-label="Duration trend">'
            f'<polyline fill="none" stroke="#8fcaff" stroke-width="2" points="{points}"/></svg>')


def _escape(value):
    return html.escape(str(value), quote=True)


def _duration(value):
    return f"{value:.2f}s" if _number(value) else "Unknown"


def _link(url, label):
    try:
        valid = urlsplit(str(url)).scheme in {"http", "https"}
    except ValueError:
        valid = False
    return f'<a href="{_escape(url)}">{_escape(label)}</a>' if valid else _escape(label)


def render_html(records, repo="IbaDemesy/RunAI"):
    records = sorted(records, key=lambda r: str(r.get("started_at", "")))
    e = _escape
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             ('<title>Test history</title><style>body{background:#161b22;color:#e6edf3;'
             'font:15px system-ui;margin:2rem}a{color:#8fcaff}table{border-collapse:collapse;'
             'width:100%}th,td{padding:.6rem;text-align:left;border-bottom:1px solid #445}'
             '.badge{border:1px solid #899;padding:.2rem .5rem;border-radius:.4rem}'
             'svg{vertical-align:middle}h2{margin-top:2rem}</style><body><h1>Test history</h1>'),
             ('<h2>Runs</h2><table><tr><th>Time</th><th>Wave</th><th>Branch</th><th>Commit</th>'
             '<th>Verdict</th><th>Duration</th><th>Suites (pass / fail / skip)</th><th>CI</th></tr>')]
    for r in records:
        git = r.get("git") or {}
        sha = str(git.get("sha", ""))
        commit = _link(f"https://github.com/{repo.strip('/')}/commit/{quote(sha, safe='')}", sha[:7])
        suites = "; ".join(f'{name}: {s.get("counts", {}).get("passed", 0)} / '
                           f'{s.get("counts", {}).get("failed", 0)} / '
                           f'{s.get("counts", {}).get("skipped", 0)}'
                           for name, s in (r.get("suites") or {}).items())
        ci = r.get("ci") or {}
        parts.append(f'<tr><td>{e(r.get("started_at", "Unknown"))}</td><td>{e(r.get("wave", ""))}</td>'
                     f'<td>{e(git.get("branch", ""))}</td><td>{commit}</td>'
                     f'<td><span class="badge">{e(r.get("verdict", "unknown"))}</span></td>'
                     f'<td>{_duration(r.get("duration_s"))}</td><td>{e(suites)}</td>'
                     f'<td>{_link(ci.get("run_url", ""), "CI") if ci else ""}</td></tr>')
    parts.append('</table><h2>Per-wave rollup</h2><table><tr><th>Wave</th><th>Runs</th>'
                 '<th>Pass rate</th><th>Median duration</th><th>Regressions</th></tr>')
    for w in compute_wave_rollups(records):
        parts.append(f'<tr><td>{e(w["wave"])}</td><td>{w["runs"]}</td>'
                     f'<td>{w["pass_rate"]:.0%}</td><td>{_duration(w["median_duration"])}</td>'
                     f'<td>{w["regressions"]}</td></tr>')
    parts.append('</table><h2>Regressions and fixes</h2><ul>')
    for change in compute_regressions(records):
        parts.append(f'<li>{e(change["run_id"])} — Regressions: '
                     f'{e(", ".join(change["regressions"]) or "None")}; Fixes: '
                     f'{e(", ".join(change["fixes"]) or "None")}</li>')
    parts.append('</ul><h2>Flaky tests (last 10 runs)</h2><p>'
                 + e(", ".join(compute_flaky(records)) or "None") + '</p>')
    parts.append('<h2>Slowest tests of latest run</h2><ol>')
    for t in slowest_tests(records[-1] if records else {}):
        parts.append(f'<li>{e(t["suite"])}: {e(t.get("id", ""))} — {_duration(t["duration_s"])}</li>')
    parts.append('</ol><h2>Suite duration trends</h2>')
    names = sorted({name for r in records for name in (r.get("suites") or {})})
    for name in names:
        values = [(r.get("suites") or {}).get(name, {}).get("duration_s") for r in records]
        parts.append(f'<p>{e(name)} {sparkline(values)}</p>')
    parts.append('</body></html>')
    return "\n".join(parts)


def render_markdown(records):
    # HTML entities also protect Markdown table separators and embedded HTML.
    def cell(value):
        return _escape(value).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    lines = ["# Test history", "", "| Wave | Runs | Pass rate | Median duration | Regressions |",
             "| --- | --- | --- | --- | --- |"]
    for w in compute_wave_rollups(records):
        lines.append(f'| {cell(w["wave"])} | {w["runs"]} | {w["pass_rate"]:.0%} | '
                     f'{_duration(w["median_duration"])} | {w["regressions"]} |')
    lines.extend(["", "## Regressions and fixes"])
    for c in compute_regressions(records):
        lines.append(f'- {cell(c["run_id"])}: Regressions: '
                     f'{cell(", ".join(c["regressions"]) or "None")}; Fixes: '
                     f'{cell(", ".join(c["fixes"]) or "None")}')
    lines.extend(["", "## Flaky tests (last 10 runs)",
                  cell(", ".join(compute_flaky(records)) or "None"), ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repo", default="IbaDemesy/RunAI", help="GitHub owner/repository")
    args = parser.parse_args(argv)
    if not args.history.is_dir():
        parser.error("--history must be an existing directory")
    records = load_records(args.history)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(render_html(records, args.repo), encoding="utf-8")
    (args.out / "summary.md").write_text(render_markdown(records), encoding="utf-8")


if __name__ == "__main__":
    main()
