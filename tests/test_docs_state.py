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


def test_notation_marks_coded_features_as_not_missing():
    text = (ROOT / "docs" / "NOTATION.md").read_text(encoding="utf-8")
    for path, phrase in [("runai/logistics", "❌ Logistique course"),
                         ("runai/safety.py", "❌ Portail"),
                         ("runai/app/voice_ws.py", "| ❌ |\n| Best use of Devin")]:
        if (ROOT / path).exists():
            assert phrase not in text, phrase
    assert "orchestrateur et taux de réussite mesurés manquants" not in text


def test_backlog_missing_test_files_are_marked_to_create():
    for line in (ROOT / "docs/product/BACKLOG.md").read_text(encoding="utf-8").splitlines():
        for ref in re.findall(r"tests/[\w/]+\.py", line):
            if not (ROOT / ref).exists():
                assert "absent" in line or "to create" in line or "new " in line, (ref, line)


def test_acceptance_tags_point_to_known_criteria():
    known = set(re.findall(r"^\| (AC-\d+) \|", (ROOT / "docs/product/ACCEPTANCE.md").read_text(encoding="utf-8"), re.MULTILINE))
    tagged = {}
    for path in (ROOT / "tests").rglob("*.py"):
        for tag in re.findall(r"AC-\d+", path.read_text(encoding="utf-8")):
            tagged.setdefault(tag, path)
    assert len(tagged) >= 15
    # AC-07..09 are journey-level IDs defined in tests/test_product_journeys.py, absent from ACCEPTANCE.md.
    assert set(tagged) <= known | {"AC-07", "AC-08", "AC-09"}, set(tagged) - known
