"""Recap to HTML (Jinja2) to PDF (headless Chrome/Chromium, no Python PDF dependency)."""

import os
import shutil
import subprocess
import tempfile
from datetime import date
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from runai.models import StepStatus

from .models import Recap

TEMPLATES = Path(__file__).parent / "templates"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TAG_LABELS = {"course": "race", "a_payer": "to pay", "info": "info", "conseil": "tip"}
CHROME_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
PDF_TIMEOUT_S = 60


class PdfRenderError(RuntimeError):
    pass


def status_label(status: StepStatus, has_price: bool) -> str:
    return {
        StepStatus.stopped_before_commitment: "ready, to pay" if has_price else "ready, to validate",
        StepStatus.completed: "ready, to validate",
        StepStatus.failed: "blocked",
        StepStatus.pending: "not launched",
        StepStatus.running: "in progress",
        StepStatus.paused: "paused",
    }[status]


def eur(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f} €"


def _date_long(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(
        eur=eur,
        eur0=lambda v: eur(v, 0),
        date_long=_date_long,
        hm=lambda d: f"{d:%H:%M}",
        dt_short=lambda d: f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year} at {d:%H:%M}",
    )
    env.globals.update(status_label=status_label, tag_labels=TAG_LABELS)
    return env


_ENV = _env()


def render_html(recap: Recap) -> str:
    """Self-contained HTML (embedded CSS and captures), printable on A4."""
    days = []
    for d, group in groupby(recap.timeline, key=lambda t: t.start.date()):
        label = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
        if d == recap.race_date:
            label += ", race day"
        days.append((label, list(group)))
    generated = recap.generated_at.astimezone(ZoneInfo(recap.calendar_timezone))
    return _ENV.get_template("recap.html.j2").render(
        r=recap, days=days, generated=generated,
        n_calendar=sum(t.in_calendar for t in recap.timeline),
    )


def chrome_path() -> str | None:
    """`RUNAI_CHROME` (or `CHROME_PATH`), otherwise the first Chrome/Chromium found on PATH."""
    for env in ("RUNAI_CHROME", "CHROME_PATH"):
        if os.environ.get(env):
            return os.environ[env]
    for name in CHROME_CANDIDATES:
        if found := shutil.which(name):
            return found
    return None


def html_to_pdf(html: str, chrome: str | None = None) -> bytes:
    """Print HTML to an A4 PDF with headless Chrome (`--print-to-pdf`)."""
    chrome = chrome or chrome_path()
    if not chrome:
        raise PdfRenderError("Chrome/Chromium not found: install Chrome or set RUNAI_CHROME.")
    with tempfile.TemporaryDirectory(prefix="runai-recap-") as tmp:
        src, out = Path(tmp) / "recap.html", Path(tmp) / "recap.pdf"
        src.write_text(html, encoding="utf-8")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
               "--disable-extensions", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
               f"--print-to-pdf={out}", src.as_uri()]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=PDF_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PdfRenderError(f"Chrome could not generate the PDF: {exc}") from exc
        if not out.exists() or out.stat().st_size == 0:
            tail = proc.stderr.decode(errors="replace")[-500:]
            raise PdfRenderError(f"Chrome did not produce a PDF (code {proc.returncode}) : {tail}")
        return out.read_bytes()


def render_pdf(recap: Recap, chrome: str | None = None) -> bytes:
    """A4 recap PDF. Blocking (~0.3-0.6 s): use `anyio.to_thread.run_sync` from FastAPI."""
    return html_to_pdf(render_html(recap), chrome)
