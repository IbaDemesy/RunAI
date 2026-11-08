import json
import subprocess
from pathlib import Path

import pytest

from scripts.test_history import backfill as history

FIXTURES = Path(__file__).parent / "fixtures" / "test_history"


def fixture_runner(args):
    name = "runs.json" if args[2] == "list" else "jobs.json"
    if name == "jobs.json":
        assert args[3] == "123"
    return json.loads((FIXTURES / name).read_text())


def test_backfill_mapping_and_skip():
    records = history.backfill(runner=fixture_runner)
    assert len(records) == 1
    item = records[0]
    assert item["verdict"] == "fail"
    assert item["source"] == "backfill"
    assert item["duration_s"] == 120
    assert item["git"] == {"sha": "abcdef0123456789", "branch": "main", "dirty": False}
    assert item["wave"] is None
    assert {k: v["verdict"] for k, v in item["suites"].items()} == {
        "ruff": "pass", "pytest": "fail", "node": "pass"}
    assert item["suites"]["node"]["duration_s"] is None
    assert all(s["counts"] is None for s in item["suites"].values())


@pytest.mark.parametrize(("conclusion", "expected"), [
    ("success", "pass"), ("failure", "fail"), ("skipped", "skip"),
    ("cancelled", "skip"), ("timed_out", "fail"), ("unknown", "error")])
def test_verdict(conclusion, expected):
    assert history.verdict(conclusion) == expected


def test_idempotent_output(tmp_path):
    for _ in range(2):
        history.main(["--out", str(tmp_path)], runner=fixture_runner)
    assert [p.name for p in tmp_path.iterdir()] == ["20260501T120000Z-abcdef0-gh123.json"]


def test_missing_run_timestamps(tmp_path):
    def runner(args):
        result = fixture_runner(args)
        if args[2] == "list":
            result[0].update(createdAt=None, updatedAt=None)
        return result
    history.main(["--out", str(tmp_path)], runner=runner)
    item = json.loads((tmp_path / "unknown-abcdef0-gh123.json").read_text())
    assert item["duration_s"] is None


@pytest.mark.parametrize(("start", "end"), [
    (None, None), (None, "2026-05-01T12:00:00Z"), ("2026-05-01T12:00:00Z", None)])
def test_missing_duration(start, end):
    assert history.duration(start, end) is None


def test_dry_run(tmp_path, capsys):
    out = tmp_path / "absent"
    history.main(["--out", str(out), "--dry-run"], runner=fixture_runner)
    assert json.loads(capsys.readouterr().out)["run_id"] == "123"
    assert not out.exists()


def test_empty_and_error(tmp_path):
    history.main(["--out", str(tmp_path)], runner=lambda args: [])
    assert not list(tmp_path.iterdir())
    def failed(args):
        raise subprocess.CalledProcessError(1, args)
    with pytest.raises(subprocess.CalledProcessError):
        history.backfill(runner=failed)


@pytest.mark.parametrize("returncode", [0, 1, None])
def test_fallback_validity(monkeypatch, returncode):
    def run(*args, **kwargs):
        if returncode is None:
            raise FileNotFoundError()
        return subprocess.CompletedProcess(args, returncode)
    monkeypatch.setattr(history.subprocess, "run", run)
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    monkeypatch.setenv("GITHUB_SHA", "abcdef0123")
    monkeypatch.setenv("WAVE", "1")
    item = history.fallback_record()
    assert item["schema_version"] == "test-history.v1"
    assert item["verdict"] == ("pass" if returncode == 0 else "fail")
    assert item["wave"] == "1"
    assert item["ci"]["run_id"] == "789"
    assert item["duration_s"] >= 0
    assert history.filename(item).endswith("-abcdef0-gh789.json")


def test_summary(tmp_path):
    records = tmp_path / "records"
    history.main(["--out", str(records)], runner=fixture_runner)
    history.main(["--fallback-summary", "--out", str(tmp_path)])
    assert "| fail | [JSON](records/" in (tmp_path / "summary.md").read_text()


@pytest.mark.parametrize("failure", [None, "--check", "--test", "missing"])
def test_node_fallback(monkeypatch, failure):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "node" and failure == "missing":
            raise FileNotFoundError()
        code = int(command[0] == "node" and command[1] == failure)
        return subprocess.CompletedProcess(command, code)
    monkeypatch.setattr(history.subprocess, "run", run)
    item = history.fallback_record()
    expected = "error" if failure == "missing" else "fail" if failure else "pass"
    assert item["suites"]["node"]["verdict"] == expected
    assert item["verdict"] == ("pass" if failure is None else "fail")
    assert any(c[:2] == ["node", "--check"] for c in calls)
    if failure is None:
        tests = next(c for c in calls if c[:2] == ["node", "--test"])
        for directory in ("web/flyover/tests/", "tests/contracts/",
                          "runai/app/static/tests/", "web/voice/tests/"):
            assert any(path.startswith(directory) for path in tests[2:])


@pytest.mark.parametrize("branch", [None, "feature/history"])
def test_fallback_branch(monkeypatch, branch):
    monkeypatch.setattr(history.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    if branch:
        monkeypatch.setenv("GITHUB_REF_NAME", branch)
    assert history.fallback_record()["git"]["branch"] == (branch or "main")


def test_publication_main_only():
    workflow = (Path(__file__).parents[1] / ".github/workflows/test-history.yml").read_text()
    publish = workflow.split("      - name: Publish history\n", 1)[1]
    assert publish.startswith("        if: github.ref == 'refs/heads/main'\n")
    upload = workflow.split("      - name: Upload record\n", 1)[1]
    assert upload.startswith("        if: always()\n")
