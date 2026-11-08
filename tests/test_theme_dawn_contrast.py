"""Rules of theme-dawn.css must keep text readable on the dark dawn surfaces."""
import re
from pathlib import Path

from scripts.check_design_tokens import resolve, root_tokens
from tests.ux_acceptance import checks

ROOT = Path(__file__).resolve().parents[1]
THEME = (ROOT / "runai/app/static/theme-dawn.css").read_text(encoding="utf-8")
TOKENS = root_tokens(THEME)


def declared(selector, prop):
    """Last `prop` value declared by a theme rule whose selector list contains `selector`."""
    value = None
    for selectors, body in re.findall(r"([^{}/]+)\{([^{}]*)\}", THEME):
        if selector in [s.strip() for s in selectors.split(",")]:
            found = re.findall(rf"(?<![\w-]){prop}:\s*([^;]+)", body)
            value = found[-1] if found else value
    return value


def test_dark_text_leftovers_are_readable_on_dark_surfaces():
    for selector in ('.course li[data-state="failed"] .cp', ".question-answer", ".source-agent"):
        colour = resolve(TOKENS, re.sub(r"\s+", "", declared(selector, "color")).strip())
        assert colour, selector
        for surface in ("surface-0", "surface-1", "surface-2"):
            assert checks.contrast_ratio(colour, resolve(TOKENS, surface)) >= 4.5, (selector, surface)


def test_running_step_border_is_visible_on_dark_card():
    colour = resolve(TOKENS, declared('.step[data-status="running"]', "border-color").strip())
    assert checks.contrast_ratio(colour, resolve(TOKENS, "surface-1")) >= 3


def test_start_marker_text_is_aa():
    css = (ROOT / "web/flyover/style.css").read_text(encoding="utf-8")
    background = re.search(r"\.marker-start\s*\{\s*background:\s*(#\w+)", css)[1]
    assert checks.contrast_ratio("#ffffff", background) >= 4.5
