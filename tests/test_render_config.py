"""Render Blueprint checks, parsed from text (PyYAML is not a runtime dependency)."""

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")
API_KEY = re.compile(r"(^|_)API_KEY(_\d+)?$")


def _strip(value: str) -> str:
    return value.split(" #")[0].strip().strip("\"'")


def _services() -> dict[str, dict]:
    """Minimal reader for the render.yaml shape: services → scalar fields + envVars list."""
    blocks = re.split(r"^  - type: ", RENDER.split("services:", 1)[1], flags=re.MULTILINE)[1:]
    services = {}
    for block in blocks:
        fields, env, current = {}, {}, None
        for line in block.splitlines()[1:]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if match := re.match(r"^ {4}(\w+):\s*(.*)$", line):
                fields[match[1]] = _strip(match[2])
            elif match := re.match(r"^ {6}- key: (\S+)\s*$", line):
                current = match[1]
                env[current] = {}
            elif (match := re.match(r"^ {8}(\w+):\s*(.*)$", line)) and current:
                env[current][match[1]] = _strip(match[2])
            else:
                raise AssertionError(f"unexpected render.yaml line: {line!r}")
        fields["envVars"] = env
        services[fields["name"]] = fields
    return services


SERVICES = _services()


def test_render_declares_live_and_demo_services():
    assert set(SERVICES) == {"runai", "runai-demo"}
    assert SERVICES["runai"]["envVars"]["RUNAI_MODE"] == {"value": "live"}
    assert SERVICES["runai-demo"]["envVars"]["RUNAI_MODE"] == {"value": "demo"}


def test_every_service_is_probed_on_health_and_single_instance():
    for name, service in SERVICES.items():
        assert service["healthCheckPath"] == "/api/health", name
        assert service["numInstances"] == "1", name
        assert service["autoDeployTrigger"] == "checksPass", name
        assert "autoDeploy" not in service, name
        assert service["envVars"]["RUNAI_PUBLIC"] == {"value": "1"}, name


def test_live_service_requires_dashboard_secrets():
    env = SERVICES["runai"]["envVars"]
    for key in ("RUNAI_BASIC_AUTH", "HAI_API_KEY", "HAI_API_KEY_2", "LINKUP_API_KEY",
                "LINKUP_API_KEY_2", "GLADIA_API_KEY", "GLADIA_API_KEY_2"):
        assert env[key] == {"sync": "false"}, key
    assert env["RUNAI_H_MAX_CONCURRENCY"] == {"value": "3"}
    assert env["RUNAI_TRACES_DIR"] == {"value": "/tmp/runai-traces"}


def test_demo_service_has_no_api_key_nor_basic_auth():
    env = SERVICES["runai-demo"]["envVars"]
    assert not [key for key in env if API_KEY.search(key)]
    assert "RUNAI_BASIC_AUTH" not in env


def test_secrets_are_never_given_a_value():
    for service in SERVICES.values():
        for key, spec in service["envVars"].items():
            if API_KEY.search(key) or key == "RUNAI_BASIC_AUTH":
                assert "value" not in spec, key


def test_every_runai_variable_is_read_by_the_app():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "runai").rglob("*.py"))
    for service in SERVICES.values():
        for key in service["envVars"]:
            if key.startswith("RUNAI_"):
                assert f'"{key}"' in sources, key


def test_start_command_factory_is_importable():
    for service in SERVICES.values():
        assert service["buildCommand"] == "pip install -r requirements.txt"
        match = re.search(r"uvicorn (\S+):(\w+) --factory .*--port \$PORT", service["startCommand"])
        assert match, service["startCommand"]
        assert callable(getattr(importlib.import_module(match[1]), match[2]))


def test_demo_mode_starts_publicly_without_basic_auth(monkeypatch):
    from runai.app.server import create_app

    for key in list(__import__("os").environ):
        if API_KEY.search(key) or key == "RUNAI_BASIC_AUTH":
            monkeypatch.delenv(key)
    monkeypatch.setenv("RUNAI_PUBLIC", "1")
    monkeypatch.setenv("RUNAI_MODE", "demo")
    assert create_app().state.service.simulated
