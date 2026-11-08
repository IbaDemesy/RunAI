"""Offline report behavior and analysis coverage."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import pytest

from scripts.test_history.render import (
    compute_flaky,
    compute_regressions,
    compute_wave_rollups,
    load_records,
    main,
    render_html,
    render_markdown,
    slowest_tests,
    sparkline,
)

FIXTURES = Path(__file__).parent / "fixtures" / "test_history"


def test_changes_and_flaky():
    records = load_records(FIXTURES)
    changes = compute_regressions(records)
    assert changes[0]["regressions"] == changes[0]["fixes"] == []
    assert changes[1]["regressions"] == ["flaky", "regression"]
    assert changes[1]["fixes"] == ["expected", "fix"]
    assert changes[2]["fixes"] == ["flaky", "regression"]
    assert changes[3]["regressions"] == ["regression"]
    assert compute_flaky(records) == ["flaky", "regression"]
    wave = compute_wave_rollups(records)[1]
    assert wave == {"wave": "beta", "runs": 2, "pass_rate": 0.5,
                    "median_duration": 12.5, "regressions": 1}
    assert slowest_tests(records[-1])[0]["id"] == "flaky"


def test_branch_isolation_and_window():
    records = load_records(FIXTURES)
    records[1]["git"]["branch"] = "other"
    assert compute_regressions(records)[1]["regressions"] == []
    assert compute_regressions(records)[1]["fixes"] == []
    assert compute_flaky(records) == []
    tail = []
    for i in range(10):
        r = copy.deepcopy(records[-1])
        r["started_at"] = f"2026-02-{i+1:02d}"
        tail.append(r)
    assert compute_flaky(records + tail) == []


@pytest.mark.parametrize("bad", ["{", "[]", '{"schema_version":"wrong"}',
                               '{"schema_version":"test-history.v1","suites":{"pytest":[]}}',
                               '{"schema_version":"test-history.v1","suites":{"pytest":{"tests":[1]}}}'])
def test_invalid_file_skipped(tmp_path, caplog, bad):
    (tmp_path / "bad.json").write_text(bad, encoding="utf-8")
    (tmp_path / "good.json").write_text((FIXTURES / "run-1.json").read_text(), encoding="utf-8")
    assert len(load_records(tmp_path)) == 1
    assert "Skipping" in caplog.text


def test_minimal_and_empty(tmp_path):
    assert load_records(tmp_path) == []
    assert compute_regressions([]) == compute_flaky([]) == compute_wave_rollups([]) == []
    assert slowest_tests({}) == []
    assert sparkline([]) == "No duration data"
    assert "Test history" in render_html([])
    record = {"schema_version": "test-history.v1"}
    (tmp_path / "minimal.json").write_text(json.dumps(record), encoding="utf-8")
    assert load_records(tmp_path) == [record]
    assert "unknown" in render_html([record])
    with pytest.raises(SystemExit):
        main(["--history", str(tmp_path / "missing"), "--out", str(tmp_path / "out")])


def test_html_safe_and_utf8(tmp_path):
    records = load_records(FIXTURES)
    records[-1]["wave"] = '<script>alert("é")</script>'
    records[-1]["ci"]["run_url"] = 'javascript:alert("bad")'
    records[-1]["suites"]["pytest"]["tests"][0]["id"] = '<img src="http://bad">'
    page = render_html(records, "example/project")
    assert '<script src' not in page
    assert '<script>' not in page
    assert 'src="http' not in page
    assert '@import' not in page
    assert 'url(http' not in page
    assert 'href="javascript:' not in page
    assert 'https://github.com/example/project/commit/abcdef0123456789' in page
    assert '&lt;script&gt;' in page and '&lt;img' in page
    assert '<svg' in page and '<polyline' in page
    assert 'Regr' in render_markdown(records)
    out = tmp_path / "dashboard"
    main(["--history", str(FIXTURES), "--out", str(out)])
    assert "Test history" in (out / "index.html").read_bytes().decode("utf-8")
    assert "# Test history" in (out / "summary.md").read_bytes().decode("utf-8")
    assert "é" in page.encode("utf-8").decode("utf-8")


def test_render_fifty_records_under_two_seconds(tmp_path):
    base = load_records(FIXTURES)[0]
    for i in range(50):
        record = dict(base, run_id=f"run-{i}", started_at=f"2026-03-{i:02d}")
        (tmp_path / f"{i}.json").write_text(json.dumps(record), encoding="utf-8")
    start = perf_counter()
    main(["--history", str(tmp_path), "--out", str(tmp_path / "out")])
    assert perf_counter() - start < 2


@pytest.mark.parametrize("entry", [["-m", "scripts.test_history.render"],
                                  ["scripts/test_history_render.py"]])
def test_cli_entrypoints(tmp_path, entry):
    result = subprocess.run([sys.executable, *entry, "--history", str(FIXTURES),
                             "--out", str(tmp_path)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "summary.md").exists()
