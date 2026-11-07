"""Fail if a tracked file carries a credential (pure-pytest fallback to gitleaks)."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "H Company key": re.compile(r"hk-[A-Za-z0-9]{16,}"),
    "Stripe secret key": re.compile(r"sk_(?:live|test)_(?!x+\b)[A-Za-z0-9]{10,}"),
    "Bearer token": re.compile(r"Bearer [A-Za-z0-9]{20,}"),
    "API key assignment": re.compile(r"\b[A-Z0-9_]*_API_KEY(?:_\d+)?=([^\s\"'`)]+)"),
}
PLACEHOLDER = re.compile(r"(?i)x{3,}|your|example|placeholder|redacted|changeme|<|\{|\$|\.\.\.")
ALLOWED_ENV_FILES = {".env.example"}


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [name for name in out.decode().split("\0") if name]


def find_leaks(name: str, text: str) -> list[str]:
    leaks = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = match.group(match.lastindex or 0)
                if label == "API key assignment" and PLACEHOLDER.search(value):
                    continue
                leaks.append(f"{name}:{lineno}: {label}")
    return leaks


def is_env_file(name: str) -> bool:
    base = Path(name).name
    return (base == ".env" or base.startswith(".env.")) and base not in ALLOWED_ENV_FILES


def test_no_env_file_tracked():
    assert [name for name in tracked_files() if is_env_file(name)] == []


def test_no_secret_in_tracked_files():
    leaks = []
    for name in tracked_files():
        path = ROOT / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            continue
        leaks += find_leaks(name, data.decode("utf-8", errors="ignore"))
    assert leaks == []


@pytest.mark.parametrize(
    "line",
    [
        "hk-" + "A1b2C3d4E5f6G7h8J9",
        "sk_" + "live_" + "51Habcdef0123456789",
        "Authorization: Bearer " + "abcdefghijklmnopqrstuv",
        "LINKUP" + "_API_KEY=lk-real-value",
        "HAI_API_KEY" + "_2=abc123def456",
    ],
)
def test_detector_flags_real_looking_secrets(line):
    assert find_leaks("f", line)


@pytest.mark.parametrize(
    "line",
    ["HAI_API_KEY=", "RESEND_API_KEY=re_xxxxxxxxx", "sk_test_xxx", "GLADIA_API_KEY=your_key",
     'HAI_API_KEY={key_value}', 'line.startswith("HAI_API_KEY=")', "hk-EXAMPLE_KEY_REDACTED"],
)
def test_detector_ignores_placeholders(line):
    assert find_leaks("f", line) == []


@pytest.mark.parametrize("name, flagged", [(".env", True), ("a/.env.local", True), (".env.example", False)])
def test_env_file_detection(name, flagged):
    assert is_env_file(name) is flagged
