import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "runai" / "app" / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent : shell non vérifié")
def test_static_javascript_syntax_and_contracts():
    for script in sorted(STATIC.rglob("*.js")):
        result = subprocess.run(
            ["node", "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        ["node", "--test", *map(str, sorted((STATIC / "tests").glob("*.test.js")))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_static_shell_has_no_fixed_city_or_distance_defaults():
    for file in STATIC.rglob("*"):
        if file.suffix in {".js", ".html"}:
            content = file.read_text(encoding="utf-8")
            for forbidden in ("Milan", "Paris", "42.195"):
                assert forbidden not in content, str(file)
