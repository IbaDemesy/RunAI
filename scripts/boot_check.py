"""Boot the ASGI app with Render's startCommand and probe the routes Render and users hit.

Catches deploy-only failures (missing dependency, import-time error, factory signature
change) before they reach Render. Partner API keys are stripped from the child env, so
no H / Linkup / Gladia credit is ever spent.

Usage: python -m scripts.boot_check --mode demo [--basic-auth user:pass] [--public]
"""

import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Self

ROOT = Path(__file__).resolve().parents[1]
BOOT_TIMEOUT_S = 20.0
PARTNER_KEY_PREFIXES = ("HAI_API_KEY", "LINKUP_API_KEY", "GLADIA_API_KEY")
APP_ENV_PREFIX = "RUNAI_"
# Blank values block `load_dotenv` (no override) from refilling keys from a local `.env`.
BLANKED_KEYS = tuple(
    name if index == 1 else f"{name}_{index}"
    for name in PARTNER_KEY_PREFIXES
    for index in range(1, 10)
)
PAGES = ("/", "/demo/live")
ASSETS = ("/static/app.js",)


class BootError(AssertionError):
    pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_command(port: int) -> list[str]:
    """`render.yaml` startCommand, bound to localhost."""
    return [
        sys.executable, "-m", "uvicorn", "runai.app.server:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(port),
    ]


def child_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(PARTNER_KEY_PREFIXES + (APP_ENV_PREFIX,))
    }
    env.update(dict.fromkeys(BLANKED_KEYS, ""))
    env["PYTHONUNBUFFERED"] = "1"
    env.update(overrides or {})
    return env


def run_to_exit(overrides: dict[str, str], timeout: float = BOOT_TIMEOUT_S) -> tuple[int | None, str]:
    """Start the app expecting it to refuse to boot; return (exit code or None if still up, stderr)."""
    process = subprocess.Popen(
        start_command(free_port()), cwd=ROOT, env=child_env(overrides),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        _, stderr = process.communicate(timeout=timeout)
        return process.returncode, stderr
    except subprocess.TimeoutExpired:
        _terminate(process)
        _, stderr = process.communicate()
        return None, stderr


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class BootedApp:
    """Context manager running the app in a subprocess until `/api/health` answers."""

    def __init__(self, overrides: dict[str, str] | None = None, timeout: float = BOOT_TIMEOUT_S):
        self.overrides = overrides or {}
        self.timeout = timeout
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._log = tempfile.TemporaryFile(mode="w+")  # noqa: SIM115 - closed in stop()
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> Self:
        self.process = subprocess.Popen(
            start_command(self.port), cwd=ROOT, env=child_env(self.overrides),
            stdout=self._log, stderr=subprocess.STDOUT, text=True,
        )
        try:
            self._wait_ready()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def output(self) -> str:
        self._log.flush()
        self._log.seek(0)
        return self._log.read()

    def fail(self, message: str) -> BootError:
        return BootError(f"{message}\n--- app output ---\n{self.output()[-4000:]}")

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise self.fail(f"app exited with code {self.process.returncode} before /api/health answered")
            try:
                if self.get("/api/health", timeout=1)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        raise self.fail(f"/api/health did not answer within {self.timeout:.0f} s")

    def get(self, path: str, auth: str | None = None, timeout: float = 5) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(self.base_url + path)
        if auth:
            request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers), error.read()

    def health(self) -> dict:
        status, _, body = self.get("/api/health")
        if status != 200:
            raise self.fail(f"/api/health returned {status}")
        return json.loads(body)

    def check_routes(self, auth: str | None = None) -> None:
        for path in PAGES + ASSETS:
            status, headers, _ = self.get(path, auth=auth)
            if status != 200:
                raise self.fail(f"GET {path} returned {status}")
            if path in PAGES and not headers.get("content-type", "").startswith("text/html"):
                raise self.fail(f"GET {path} content-type is {headers.get('content-type')!r}")

    def stop(self) -> None:
        if self.process is not None:
            _terminate(self.process)
            self.process = None


def write_demo_trace(path: Path) -> Path:
    from runai.app.fakes import DEMO_RACES
    from runai.app.replay import ReplayTrace

    ReplayTrace(label="Tokyo", race=DEMO_RACES["tokyo"]).dump(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("demo", "replay", "live"), default="demo")
    parser.add_argument("--replay-trace", type=Path, help="replay.v1 file (default: generated Tokyo trace)")
    parser.add_argument("--basic-auth", help="user:pass, sets RUNAI_BASIC_AUTH")
    parser.add_argument("--public", action="store_true", help="sets RUNAI_PUBLIC=1")
    args = parser.parse_args(argv)

    overrides = {"RUNAI_MODE": args.mode}
    if args.public:
        overrides["RUNAI_PUBLIC"] = "1"
    if args.basic_auth:
        overrides["RUNAI_BASIC_AUTH"] = args.basic_auth
    with tempfile.TemporaryDirectory() as tmp:
        overrides["RUNAI_TRACES_DIR"] = tmp
        if args.mode == "replay":
            trace = args.replay_trace or write_demo_trace(Path(tmp) / "replay.json")
            overrides["RUNAI_REPLAY_TRACE"] = str(trace)
        try:
            with BootedApp(overrides) as app:
                health = app.health()
                if not health.get("ok") or health.get("mode") != args.mode:
                    raise app.fail(f"unexpected /api/health payload: {health}")
                app.check_routes(auth=args.basic_auth)
        except BootError as error:
            print(f"boot check FAILED ({args.mode}): {error}", file=sys.stderr)
            return 1
    print(f"boot check OK ({args.mode}): /api/health, {', '.join(PAGES + ASSETS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
