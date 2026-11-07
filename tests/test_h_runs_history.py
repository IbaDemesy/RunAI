import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.test_history.h_runs import extract_runs, markdown_summary

FIXTURES = Path(__file__).parent / "fixtures" / "traces"


def test_synthetic_history():
    runs = {r["mission_id"]: r for r in extract_runs(FIXTURES)}
    assert len(runs) == 5
    live = runs["live"]
    assert live == {
        "schema_version": "h-runs.v1", "mission_id": "live", "step_kind": "registration",
        "session_id": "s-live", "platform": "njuko.com", "status": "stopped_before_commitment",
        "outcome": "success", "stop_point": "payment", "steps": 22, "duration_s": 30,
        "total_cost": 0.12, "error_code": None, "recorded_at": "2026-11-07T01:00:30+00:00",
        "mode": "live",
    }
    assert runs["demo"]["mode"] == "demo"
    assert runs["demo"]["platform"] == "all.accor.com"
    assert runs["demo"]["steps"] is None
    assert runs["captcha"]["error_code"] == "captcha"
    assert runs["captcha"]["status"] == "failed"
    assert runs["timeout"]["duration_s"] == 60
    assert runs["timeout"]["error_code"] == "timed_out"
    missing = runs["missing"]
    assert missing["platform"] == "unknown"
    for key in ("step_kind", "status", "steps", "duration_s", "total_cost", "mode", "recorded_at"):
        assert missing[key] is None
    summary = markdown_summary(list(runs.values()))
    assert "| njuko.com | 2 | 50.0% | 13.000 | 21.000 | 0.070 |" in summary
    assert "| all.accor.com | 1 | 100.0% | — | 8.000 | — |" in summary


def test_raw_events_multiple_sessions_and_step_done(tmp_path):
    events = [
        {"at": "2026-01-01T00:00:00Z", "data": {"h_session_id": "one", "step": "transport"}},
        {"at": "2026-01-01T00:00:02Z", "data": {"h_session_id": "two", "step": "registration"}},
        {"at": "2026-01-01T00:00:03Z", "data": {"h_session_id": "one", "event": {
            "data": {"metrics": {"steps": 3, "total_cost": 0.5}}}}},
        {"at": "2026-01-01T00:00:04Z", "data": {"session_id": "one", "event": {
            "data": {"metadata": {"url": "https://all.accor.com/page"}, "outcome": "success"}}}},
        {"at": "2026-01-01T00:00:05Z", "type": "step_done", "data": {
            "step": "transport", "status": "stopped_before_commitment", "provenance": {"mode": "replay"}}},
    ]
    (tmp_path / "multi.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    one, two = extract_runs(tmp_path)
    assert one["steps"] == 3
    assert one["total_cost"] == 0.5
    assert one["platform"] == "all.accor.com"
    assert one["duration_s"] == 5
    assert one["mode"] == "replay"
    assert one["status"] == "stopped_before_commitment"
    assert two["session_id"] == "two"
    assert two["duration_s"] == 0
    assert two["mode"] is None


def test_empty_history(tmp_path):
    assert extract_runs(tmp_path) == []
    assert len(markdown_summary([]).splitlines()) == 2


def test_cli_redacts_before_writing(tmp_path, monkeypatch, capsys):
    from scripts.test_history.h_runs import main

    secret = "synthetic-key-for-redaction"
    monkeypatch.setenv("HAI_API_KEY", secret)
    (tmp_path / "trace.jsonl").write_text(json.dumps({"data": {
        "h_session_id": secret, "provenance": {"mode": "live"}, "error_code": secret,
    }}))
    out = tmp_path / "output.jsonl"
    monkeypatch.setattr(sys, "argv", ["h_runs", "--traces", str(tmp_path), "--out", str(out), "--md"])
    main()
    contents = out.read_text()
    assert secret not in contents
    assert json.loads(contents)["session_id"] == "[REDACTED]"
    assert "unknown" in capsys.readouterr().out


def test_cli_module(tmp_path):
    out = tmp_path / "history.jsonl"
    result = subprocess.run([sys.executable, "-m", "scripts.h_runs", "--traces", str(FIXTURES),
                             "--out", str(out), "--md"], capture_output=True, text=True, check=True)
    assert len(out.read_text().splitlines()) == 5
    assert "| trenitalia.com |" in result.stdout


def test_cli_rejects_missing_directory(tmp_path, monkeypatch, capsys):
    from scripts.test_history.h_runs import main

    monkeypatch.setattr(sys, "argv", ["h_runs", "--traces", str(tmp_path / "absent"),
                                     "--out", str(tmp_path / "history.jsonl")])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "existing directory" in capsys.readouterr().err
