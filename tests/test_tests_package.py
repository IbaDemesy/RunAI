import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_tests_package_wins_over_global_tests_package(tmp_path):
    """J12: a regular `tests` package elsewhere on sys.path must not shadow ours."""
    shadow = tmp_path / "site" / "tests"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("SHADOW = True\n")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); sys.path.append(sys.argv[2]);"
        "import tests, tests.journey_helpers, tests.e2e.helpers;"
        "assert not hasattr(tests, 'SHADOW'), tests.__file__"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(tmp_path / "site")],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
