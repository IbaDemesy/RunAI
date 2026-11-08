"""Copy inventory coverage and scanner regression checks."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/design/scripts/copy_coverage.py"
DECK = ROOT / "docs/design/COPY_DECK.md"
spec = importlib.util.spec_from_file_location("copy_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def test_copy_deck_coverage():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], check=False, capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("0 missing") == 2
    assert not any(word in DECK.read_text() for word in ("Milan", "Paris", "42.195"))


def test_js_inventory_filters_code_and_comments():
    source = '''// "Not UI copy"
    /* l'agent says "Not copy either" */
    el("h1", "Where do you want to run?", "hero");
    button("Envoyer", submit);
    el("p", "Dites-m’en un peu plus sur votre projet.");
    button("Exporter ", submit);
    el("p", "Your race, your goal, your trip.");
    const status = {running: "en cours"};
    const route = "/api/missions";
    const url = "https://example.org";
    const event = "mission_status";
    const selector = ".agent-live[open]";
    const method = "showChapter";
    const type = "application/json";
    const css = "agent-live";
    el("div", null, "trace corrections");
    node.rel = "noopener noreferrer";
    const header = "Content-Type";
    '''
    assert coverage.js_strings(source) == {
        "Where do you want to run?", "Envoyer", "en cours",
        "Dites-m’en un peu plus sur votre projet.", "Exporter ",
        "Your race, your goal, your trip.",
    }
    assert coverage.js_strings("") == set()


def test_html_inventory(tmp_path):
    page = tmp_path / "live.html"
    page.write_text('''<style>.red { color: red; }</style>
    <h1>Your turn</h1><input placeholder="Type here" aria-label="Your answer">
    <img alt="Race route"><a title="Open race">Source</a>
    <script>const label = "En attente"; const id = "action";</script>''')
    assert coverage.extract(page) == {
        "Your turn", "Type here", "Your answer", "Race route", "Open race",
        "Source", "En attente",
    }


def test_missing_copy_fails_and_only_current_column_counts(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("| example | Different source | Où voulez-vous courir ? | Hero | 80 | — |\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--deck", str(deck)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "Missing: Où voulez-vous courir ?" in result.stdout
    assert coverage.current_copy(deck.read_text()) == {"Different source"}
    assert coverage.current_copy("") == set()
