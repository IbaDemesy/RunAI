"""Récap du week-end de course : PDF + .ics à partir d'une mission RunAI.

API :

- `recap_from_mission(race, profile, steps, ...) -> Recap`
- `render_html(recap) -> str`, `render_pdf(recap) -> bytes` (Chrome headless), `render_ics(recap) -> bytes`
- `demo_recap()` : exemple fictif (Wizz Air Milano Marathon 2027)

Voir docs/RECAP.md.
"""

from .build import default_timeline, recap_from_mission
from .demo import demo_recap
from .ics import render_ics
from .models import FieldRow, KeyFact, Recap, RecapMission, RecapSource, TimelineItem
from .render import PdfRenderError, render_html, render_pdf

__all__ = [
    "FieldRow",
    "KeyFact",
    "PdfRenderError",
    "Recap",
    "RecapMission",
    "RecapSource",
    "TimelineItem",
    "default_timeline",
    "demo_recap",
    "recap_from_mission",
    "render_html",
    "render_ics",
    "render_pdf",
]
