"""Heuristic UI-copy inventory; no JavaScript runtime or third-party dependencies."""

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = ("runai/app/static/app.js", "runai/app/static/live.html")
LITERAL = re.compile(r'([\"\'`])((?:\\.|(?!\1).)*?)\1', re.DOTALL)
SINGLE = {
    "Source", "Transport", "Budget", "Replay", "Pause", "RunAI", "Performance",
    "Inscription", "Envoyer", "Explorer", "Lecture", "Agrandir", "Parler", "Ville",
    "Course", "Nuits", "Avion", "Train", "Voiture", "Autocar", "Paiement",
    "Consentement", "Inconnu", "Illustratif", "Ouverte", "inconnu", "inconnue",
    "en attente", "en cours", "en pause", "sans objet", " nuits", " nuit", "Depuis ",
    " (nouvel onglet)", "RunAI cherche pour vous…", " € max", "Marche", "Vol",
    "Partiel", "illustratif", "matin", "moins de 3h30", "3h30–4h", "plus de 4h",
}


def looks_like_copy(value: str) -> bool:
    """Keep natural-language literals, not selectors, protocol values or code."""
    text = value.strip()
    if not text or not any(c.isalpha() for c in text):
        return False
    if re.match(r"(?:https?:|/|about:|data:|#[\w-])", text):
        return False
    if value in SINGLE or text in SINGLE:
        return True
    if text == "use strict" or re.fullmatch(r"[a-z0-9_.:#/\[\]()> =,-]+", text):
        return False
    return text in SINGLE or bool(re.search(r"[À-ÿ]|[A-Z][a-z]+(?: |…|[.!?])", text))


def js_strings(source: str) -> set[str]:
    # Comments are skipped by the same scanner, so apostrophes in prose cannot
    # consume the next literal. Template expressions remain verbatim copy slots.
    scanner = re.compile(r"//[^\n]*|/\*.*?\*/|" + LITERAL.pattern, re.DOTALL)
    return {
        match.group(2).replace("\\'", "'").replace('\\"', '"')
        for match in scanner.finditer(source)
        if match.group(2) is not None and looks_like_copy(match.group(2))
    }


class CopyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.strings: set[str] = set()
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        for name, value in attrs:
            if name in {"placeholder", "aria-label", "title", "alt"} and value:
                self.strings.add(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and looks_like_copy(data):
            self.strings.add(data.strip())


def extract(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    if path.suffix != ".html":
        return js_strings(source)
    parser = CopyHTMLParser()
    parser.feed(source)
    for script in re.findall(r"<script\b[^>]*>(.*?)</script>", source, re.DOTALL):
        parser.strings.update(js_strings(script))
    return parser.strings


def current_copy(deck: str) -> set[str]:
    rows = (line.split(" | ") for line in deck.splitlines() if line.startswith("| "))
    return {cells[1].replace("&#124;", "|") for cells in rows if len(cells) == 6}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", type=Path, default=ROOT / "docs/design/COPY_DECK.md")
    args = parser.parse_args()
    inventory = current_copy(args.deck.read_text(encoding="utf-8"))
    missing_count = 0
    for relative in REQUIRED:
        strings = extract(ROOT / relative)
        missing = sorted(strings - inventory)
        print(f"{relative}: {len(strings)} strings, {len(missing)} missing")
        for value in missing:
            print(f"  Missing: {value}")
        missing_count += len(missing)
    return int(bool(missing_count))


if __name__ == "__main__":
    raise SystemExit(main())
