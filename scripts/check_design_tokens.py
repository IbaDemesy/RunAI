"""Check docs/design/tokens.css: contrast pairs, legacy names and the UX acceptance palette contract.

Usage, from the repository root:
    python -m scripts.check_design_tokens            # verify, exit 1 on failure
    python -m scripts.check_design_tokens --markdown # print the contrast table for DESIGN_SYSTEM.md
"""

import argparse
import re
import sys
from pathlib import Path

from tests.ux_acceptance import checks

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "docs/design/tokens.css"
STYLE = ROOT / "runai/app/static/style.css"

DARK = ("surface-0", "surface-1", "surface-2")
STATUSES = ("pending", "running", "paused", "waiting", "stopped", "completed", "failed")
PARTNERS = ("h", "linkup", "gladia", "holo", "devin")
REQUIRED = [f"status-{s}-{part}" for s in STATUSES for part in ("bg", "fg")]
REQUIRED += [f"partner-{p}" for p in PARTNERS] + list(DARK) + ["focus", "motion-fast", "motion-chapter"]


def pairs():
    """(group, foreground, background, minimum): text pairs need 4.5, non-text UI parts 3."""
    rows = [("Text on dark", fg, bg, 4.5) for fg in ("chalk", "mist", "haze", "sun", "text-error", "text-success") for bg in DARK]
    rows += [("Partner label", f"partner-{p}", bg, 4.5) for p in PARTNERS for bg in DARK]
    rows += [("Status chip", f"status-{s}-fg", f"status-{s}-bg", 4.5) for s in STATUSES]
    rows += [("Button", f"button-{v}-fg", f"button-{v}-bg", 4.5) for v in ("primary", "secondary", "danger")]
    rows += [("Button", "button-quiet-fg", bg, 4.5) for bg in DARK]
    rows += [("Bright fill", "ink", bg, 4.5) for bg in ("card", "paper", "paper-2", "accent", "gold-soft")]
    rows += [("Legacy light", fg, bg, 4.5) for fg in ("ink-2", "ink-3") for bg in ("paper", "paper-2", "card")]
    rows += [("Legacy light", "#fff", "ink", 4.5), ("Legacy light", "button-text", "button-bg", 4.5)]
    rows += [("Legacy light", "ok", "#e3f1e8", 4.5), ("Legacy light", "bad", "#fbe6e8", 4.5)]
    rows += [("Non-text", "focus", bg, 3) for bg in DARK]
    rows += [("Non-text", "focus-on-bright", bg, 3) for bg in ("sun", "chalk")]
    rows += [("Non-text", f"mode-{m}", bg, 3) for m in ("live", "demo", "replay") for bg in DARK]
    rows += [("Non-text", "border-strong", bg, 3) for bg in ("surface-0", "surface-1")]
    return rows


def root_tokens(source):
    root = re.search(r":root\s*\{([^}]+)", source)
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", root[1] if root else ""))


def resolve(tokens, name):
    value = tokens.get(name, name).strip()
    for _ in range(len(tokens)):
        ref = re.fullmatch(r"var\(--([\w-]+)\)", value)
        if not ref:
            break
        value = tokens.get(ref[1], "").strip()
    return value if re.fullmatch(r"#[\da-fA-F]{3}(?:[\da-fA-F]{3})?", value) else None


def table(source):
    tokens = root_tokens(source)
    rows = []
    for group, fg, bg, minimum in pairs():
        a, b = resolve(tokens, fg), resolve(tokens, bg)
        ratio = checks.contrast_ratio(a, b) if a and b else 0.0
        rows.append((group, fg, a, bg, b, ratio, minimum))
    return rows


def errors(source, style_source=None):
    tokens = root_tokens(source)
    found = [f"missing token --{name}" for name in REQUIRED if name not in tokens]
    for group, fg, a, bg, b, ratio, minimum in table(source):
        if not a or not b:
            found.append(f"unresolved {fg}/{bg}")
        elif ratio < minimum:
            found.append(f"{fg}/{bg}: {ratio:.2f} < {minimum}")
    found += [f"ux_acceptance: {e}" for e in checks.contrasts(source)]
    if style_source is not None:
        legacy = set(re.findall(r"--([a-zA-Z][\w-]*)", style_source))
        found += [f"style.css variable --{name} missing from tokens.css" for name in sorted(legacy - set(tokens))]
    return found


def _cell(name, value):
    return name if name.startswith("#") else f"`--{name}` {value}"


def markdown(source):
    lines = ["| Group | Foreground | Background | Ratio | Min |", "| --- | --- | --- | ---: | ---: |"]
    for group, fg, a, bg, b, ratio, minimum in table(source):
        lines.append(f"| {group} | {_cell(fg, a)} | {_cell(bg, b)} | {ratio:.2f} | {minimum} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    source = TOKENS.read_text(encoding="utf-8")
    if args.markdown:
        print(markdown(source))
        return 0
    problems = errors(source, STYLE.read_text(encoding="utf-8"))
    for problem in problems:
        print(problem)
    rows = table(source)
    print(f"{len(rows)} pairs checked, lowest ratio {min(r[5] for r in rows):.2f}; {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
