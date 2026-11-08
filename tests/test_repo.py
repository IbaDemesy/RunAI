import importlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_sdks_import():
    for module_name in ("hai_agents", "gladiaio_sdk", "linkup"):
        importlib.import_module(module_name)


def test_env_example_declares_only_empty_required_keys():
    lines = [
        line.strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    declarations = [line.partition("=") for line in lines]
    keys = [key.strip() for key, separator, _ in declarations if separator]
    assert sorted(keys) == sorted([
        "GLADIA_API_KEY", "GLADIA_API_KEY_2", "HAI_API_KEY", "HAI_API_KEY_2", "LINKUP_API_KEY",
        "LINKUP_API_KEY_2", "RUNAI_BASIC_AUTH", "RUNAI_H_MAX_STEPS", "RUNAI_H_MAX_TIME_S", "RUNAI_MODE",
        "RUNAI_PUBLIC", "RUNAI_TRACES_DIR",
    ])
    assert all(separator and not value.strip() for _, separator, value in declarations)


def test_tracked_files_do_not_contain_api_key_patterns():
    patterns = (
        ("h-company", re.compile("hk-" + r"[0-9a-f]{20,}")),
        ("gladia", re.compile("sk_gladia_" + r"[0-9a-f]{16,}")),
        ("linkup", re.compile("lk_" + r"[A-Za-z0-9]{30,}")),
    )
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    findings = []
    for relative_path in tracked_files:
        path = ROOT / relative_path
        if not path.is_file():
            continue
        content = path.read_bytes()
        for label, pattern in patterns:
            if pattern.search(content.decode("latin-1")):
                findings.append(f"{relative_path} ({label})")
    assert not findings, f"Potential API key patterns found in tracked files: {findings}"
