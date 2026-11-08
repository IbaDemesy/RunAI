"""Boot smoke test: run the exact Render startCommand in a subprocess and probe it."""

import re

import pytest

from scripts.boot_check import (
    ROOT,
    BootedApp,
    run_to_exit,
    start_command,
    write_demo_trace,
)

pytest.importorskip("uvicorn", reason="uvicorn not installed: pip install -r requirements.txt")


def test_start_command_matches_render_yaml():
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    command = re.search(r"^\s*startCommand:\s*(.+)$", render, re.MULTILINE).group(1).split()
    ours = start_command(0)[2:]
    assert command[0] == "uvicorn" and command[1:-4] == ours[1:-4], command
    assert command[-4::2] == ["--host", "--port"]


def assert_health(app: BootedApp, mode: str) -> None:
    health = app.health()
    assert health["ok"] is True and health["mode"] == mode, health


def test_demo_mode_boots_and_serves_pages(tmp_path):
    with BootedApp({"RUNAI_MODE": "demo", "RUNAI_TRACES_DIR": str(tmp_path)}) as app:
        assert_health(app, "demo")
        app.check_routes()


def test_replay_mode_boots_from_trace(tmp_path):
    trace = write_demo_trace(tmp_path / "replay.json")
    env = {"RUNAI_MODE": "replay", "RUNAI_REPLAY_TRACE": str(trace), "RUNAI_TRACES_DIR": str(tmp_path)}
    with BootedApp(env) as app:
        assert_health(app, "replay")
        app.check_routes()


def test_public_live_without_basic_auth_refuses_to_boot(tmp_path):
    code, stderr = run_to_exit(
        {"RUNAI_MODE": "live", "RUNAI_PUBLIC": "1", "RUNAI_TRACES_DIR": str(tmp_path)}
    )
    assert code not in (None, 0), f"app kept running or exited 0\n{stderr[-4000:]}"
    assert "RUNAI_BASIC_AUTH" in stderr, stderr[-4000:]


def test_basic_auth_guards_pages_but_not_health(tmp_path):
    env = {"RUNAI_MODE": "demo", "RUNAI_BASIC_AUTH": "u:p", "RUNAI_TRACES_DIR": str(tmp_path)}
    with BootedApp(env) as app:
        status, headers, _ = app.get("/")
        assert status == 401, status
        assert "basic" in headers.get("www-authenticate", "").lower(), headers
        assert_health(app, "demo")
        app.check_routes(auth="u:p")
