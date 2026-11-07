"""Heuristic UI-copy inventory; no JavaScript runtime or third-party dependencies."""

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = ("runai/app/static/app.js", "runai/app/static/live.html")
LITERAL = re.compile(r'([\"\'`])((?:\\.|(?!\1).)*?)\1', re.DOTALL)


def looks_like_copy(value: str) -> bool:
    """Keep natural-language literals, not selectors, protocol values or code."""
    text = value.strip()
    if not text or not any(c.isalpha() for c in text):
        return False
    if re.match(r"(?:[a-z][a-z0-9+.-]*:|[/#.]|\([^)]*:[^)]*\))", text):
        return False
    if text == "use strict" or re.fullmatch(r"[A-Z_]+", text):
        return False
    if re.fullmatch(r"[\w.-]+/[\w.+-]+", text):
        return False
    if re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}", text):
        return False
    if re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z][a-z]+)+", text):
        return False
    if re.fullmatch(r"\w+", text) and (
        "_" in text or re.search(r"^[a-z].*[A-Z]", text)
    ):
        return False
    if re.fullmatch(r"[a-z0-9-]+(?: [a-z0-9-]+)*", text) and "-" in text:
        return False
    if re.search(r"[\[\]#]", text) or re.fullmatch(
        r"[a-z]+(?::[a-z-]+)?(?:,\s*[a-z]+(?::[a-z-]+)?)+", text
    ):
        return False
    words = re.findall(r"[^\W\d_]+", text)
    return (
        any(c.isalpha() and not c.isascii() for c in text)
        or any(c in text for c in "’…«»")
        or any(word[0].isupper() for word in words)
        or len(re.findall(r"[^\W\d_]+(?:\s+)[^\W\d_]+", text)) > 0
    )


def js_strings(source: str) -> set[str]:
    # Comments are skipped by the same scanner, so apostrophes in prose cannot
    # consume the next literal. Template expressions remain verbatim copy slots.
    scanner = re.compile(r"//[^\n]*|/\*.*?\*/|" + LITERAL.pattern, re.DOTALL)
    strings = set()
    for match in scanner.finditer(source):
        value = match.group(2)
        if value is None or not looks_like_copy(value):
            continue
        prefix = source[source.rfind("\n", 0, match.start()) + 1:match.start()]
        if re.search(r"\.(?:className|rel)\s*=\s*$", prefix):
            continue
        # The local el(tag, text, className) helper's last argument is CSS.
        if (
            re.fullmatch(r"[a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*", value)
            and re.search(r"\bel\(", prefix)
            and prefix.count(",") >= 2
            and re.match(r"\s*\)", source[match.end():])
        ):
            continue
        strings.add(value.replace("\\'", "'").replace('\\"', '"'))
    return strings


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
