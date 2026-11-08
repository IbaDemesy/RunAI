"""S4: partner documents (credits, promo codes) must never be committed again."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {".md", ".txt"}


def _tracked_infos_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "Infos"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def test_infos_contains_only_text_files():
    offenders = [
        path for path in _tracked_infos_files() if Path(path).suffix.lower() not in ALLOWED_SUFFIXES
    ]
    assert offenders == [], f"binary/PDF files under Infos/: {offenders}"


def test_no_pdf_tracked_anywhere():
    out = subprocess.run(["git", "ls-files", "*.pdf", "*.PDF"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.split() == [], f"tracked PDFs: {out.stdout.split()}"
