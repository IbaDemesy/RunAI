import json
import subprocess
from pathlib import Path

import pytest

from scripts.test_history import check
from scripts.test_history.schema import Git, RunRecord, Suite


def test_ruff():
    assert check.parse_ruff("[]").verdict == "pass"
    suite = check.parse_ruff(json.dumps([{
        "filename": "a.py", "location": {"row": 2, "column": 3},
        "code": "F401", "message": "Unused import",
    }]))
    assert suite.verdict == "fail"
    assert suite.failures[0].id == "a.py:2:3:F401"
    assert suite.counts.failed == 1


def test_junit_outcomes():
    suite = check.parse_junit('''<testsuites><testsuite>
      <testcase classname="a" name="pass" time="0.25"/>
      <testcase classname="a" name="non_strict_xpass"/>
      <testcase classname="a" name="skip"><skipped message="reason"/></testcase>
      <testcase classname="a" name="xfail"><skipped type="pytest.xfail" message="expected"/></testcase>
      <testcase classname="a" name="xfail_message"><skipped message="pytest.xfail"/></testcase>
      <testcase classname="a" name="xpass"><failure message="[XPASS(strict)] reason"/></testcase>
      <testcase classname="a" name="fail"><failure message="bad"/></testcase>
      <testcase classname="a" name="error"><error message="broken"/></testcase>
    </testsuite></testsuites>''')
    assert suite.verdict == "fail"
    assert suite.counts.model_dump() == {"passed": 2, "failed": 2, "skipped": 1, "xfailed": 2, "xpassed": 1, "errors": 1}
    assert suite.tests[0].id == "a::pass"
    assert suite.tests[0].duration_s == .25
    assert len(suite.failures) == 3


def test_junit_empty_and_pass():
    assert check.parse_junit("<testsuite/>").verdict == "pass"
    assert check.parse_junit('<testsuite><testcase name="ok"/></testsuite>').counts.passed == 1


def test_tap_nested_and_directives():
    suite = check.parse_tap('''TAP version 13
# Subtest: parent
    # Subtest: child
    ok 1 - child
      ---
      duration_ms: 100
      ...
    1..1
ok 1 - parent
  ---
  duration_ms: 250
  ...
ok 2 - skipped # SKIP unavailable
not ok 3 - expected # TODO later
not ok 4 - broken
  ---
  error: 'failure'
  ...
1..4
''')
    assert suite.verdict == "fail"
    assert len(suite.tests) == 4
    assert suite.tests[0].duration_s == .25
    assert suite.counts.model_dump() == {"passed": 1, "failed": 1, "skipped": 1, "xfailed": 1, "xpassed": 0, "errors": 0}
    assert suite.failures[0].message == "broken"


@pytest.mark.parametrize("output", ["1..0 # no tests", "ok 1 - works\n1..1"])
def test_tap_pass(output):
    assert check.parse_tap(output).verdict == "pass"


def test_tap_passing_todo_is_xpassed():
    suite = check.parse_tap("ok 1 - fixed # TODO verify\nnot ok 2 - pending # TODO later\n1..2")
    assert suite.verdict == "pass"
    assert suite.counts.xpassed == 1
    assert suite.counts.xfailed == 1
    assert [test.outcome for test in suite.tests] == ["xpassed", "xfailed"]
    assert suite.failures == []


@pytest.mark.parametrize("parser, output", [
    (check.parse_ruff, "{}"), (check.parse_ruff, "invalid"),
    (check.parse_junit, "<bad/>"), (check.parse_junit, "invalid"),
    (check.parse_tap, "garbage"), (check.parse_tap, "ok 1 - missing\n1..2"),
])
def test_unparsable(parser, output):
    with pytest.raises((ValueError, TypeError, check.ET.ParseError)):
        parser(output)


def test_node_absent(monkeypatch):
    monkeypatch.setattr(check.shutil, "which", lambda name: None)
    suite = check.run_suite("node")
    assert suite.verdict == "skip"
    assert suite.reason == "node is not on PATH"


@pytest.mark.parametrize("name", ["ruff", "pytest", "node"])
def test_runner_errors(monkeypatch, name):
    monkeypatch.setattr(check.shutil, "which", lambda name: "/bin/node")

    def fail(*args, **kwargs):
        raise OSError("Tool unavailable")

    monkeypatch.setattr(check.subprocess, "run", fail)
    suite = check.run_suite(name)
    assert suite.verdict == "error"
    assert suite.reason == "Tool unavailable"


@pytest.mark.parametrize("name, output", [("ruff", "[]"), ("node", "ok 1 - test\n1..1")])
def test_runner_exit_mismatch(monkeypatch, name, output):
    monkeypatch.setattr(check.shutil, "which", lambda name: "/bin/node")
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, output, "crashed"))
    assert check.run_suite(name).verdict == "error"


@pytest.mark.parametrize("verdict, exit_code", [("pass", 0), ("fail", 1), ("error", 1)])
def test_record(monkeypatch, tmp_path, capsys, verdict, exit_code):
    calls = []

    def run(name):
        calls.append(name)
        return Suite(verdict=verdict)

    monkeypatch.setattr(check, "run_suite", run)
    monkeypatch.setattr(check, "git_info", lambda: Git(sha="abcdef012345", branch="test", dirty=True))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("RUNAI_WAVE", "environment-wave")
    assert check.main(["--out", str(tmp_path), "--skip", "node"]) == exit_code
    assert calls == ["ruff", "pytest"]
    paths = list(tmp_path.glob("*.json"))
    assert len(paths) == 1
    record = RunRecord.model_validate_json(paths[0].read_text())
    assert record.schema_version == "test-history.v1"
    assert record.wave == "environment-wave"
    assert record.ci is None
    assert record.suites.node.reason == "Skipped by flag"
    assert record.verdict == ("pass" if exit_code == 0 else "fail")
    assert len(capsys.readouterr().out.splitlines()) == 5


def test_repeatable_skip_and_wave(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "git_info", lambda: Git(sha="abcdef0", branch="test", dirty=False))
    monkeypatch.setenv("RUNAI_WAVE", "ignored")
    assert check.main(["--out", str(tmp_path), "--wave", "explicit", "--skip", "node", "--skip", "pytest", "--skip", "ruff"]) == 0
    record = RunRecord.model_validate_json(next(tmp_path.glob("*.json")).read_text())
    assert record.wave == "explicit"


def test_records_never_overwrite(monkeypatch, tmp_path):
    class FrozenDateTime:
        @staticmethod
        def now(tz):
            return check.datetime.fromisoformat("2026-11-07T21:25:01+00:00")

    frozen = FrozenDateTime.now(check.UTC)
    monkeypatch.setattr(FrozenDateTime, "now", staticmethod(lambda tz: frozen))
    monkeypatch.setattr(check, "datetime", FrozenDateTime)
    monkeypatch.setattr(check, "git_info", lambda: Git(sha="abcdef0", branch="test", dirty=False))
    args = ["--out", str(tmp_path), "--skip", "ruff", "--skip", "pytest", "--skip", "node"]
    assert check.main(args) == 0
    first = tmp_path / "20261107T212501Z-abcdef0.json"
    original = first.read_bytes()
    assert check.main(args) == 0
    assert first.read_bytes() == original
    paths = sorted(tmp_path.glob("*.json"))
    assert len(paths) == 2
    for path in paths:
        record = RunRecord.model_validate_json(path.read_text())
        assert record.run_id == path.stem


def test_ci(monkeypatch):
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "42", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/repo"}.items():
        monkeypatch.setenv(key, value)
    assert check.ci_info().run_url == "https://github.com/owner/repo/actions/runs/42"


def test_committed_schema():
    from scripts.test_history.schema import RunRecord

    schema = Path(check.ROOT / "docs/test-history.schema.json").read_text()
    assert json.loads(schema) == RunRecord.model_json_schema()
