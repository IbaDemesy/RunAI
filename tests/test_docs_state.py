"""J11: product docs must match the real repository state."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "docs" / "product" / "BACKLOG.md", ROOT / "docs" / "NOTATION.md",
        ROOT / "docs" / "design" / "QUESTIONS_AND_FRAMING.md", ROOT / "docs" / "design" / "VOICE_INPUT.md"]


def test_no_stale_file_names_in_docs():
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "test_framing_extraction_en.py" not in text, doc
        assert not re.search(r"static/styles\.css", text), doc


def test_notation_does_not_deny_existing_orchestrator_and_ux():
    assert (ROOT / "runai/app/mission.py").exists() and (ROOT / "runai/app/voice_ws.py").exists()
    text = (ROOT / "docs" / "NOTATION.md").read_text(encoding="utf-8")
    assert "❌ Orchestrateur" not in text
    assert "conçus, pas codés" not in text


def test_backlog_english_only_guard_status_matches_tree():
    row = next(line for line in (ROOT / "docs/product/BACKLOG.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("| PB-04 "))
    if not (ROOT / "tests/test_english_only.py").exists():
        assert row.rstrip().endswith("| todo |") and "absent" in row
