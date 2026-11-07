"""Recap → HTML (Jinja2) → PDF (Chrome/Chromium headless, sans dépendance Python)."""

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
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
TAG_LABELS = {"course": "course", "a_payer": "à payer", "info": "info", "conseil": "conseil"}
CHROME_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
PDF_TIMEOUT_S = 60


class PdfRenderError(RuntimeError):
    pass


def status_label(status: StepStatus, has_price: bool) -> str:
    return {
        StepStatus.stopped_before_commitment: "prêt, à payer" if has_price else "prêt, à valider",
        StepStatus.completed: "prêt, à valider",
        StepStatus.failed: "bloqué",
        StepStatus.pending: "non lancé",
        StepStatus.running: "en cours",
        StepStatus.paused: "en pause",
    }[status]


def eur(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",") + " €"


def _date_long(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(
        eur=eur,
        eur0=lambda v: eur(v, 0),
        date_long=_date_long,
        hm=lambda d: f"{d:%H:%M}",
        dt_short=lambda d: f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year} à {d:%H:%M}",
    )
    env.globals.update(status_label=status_label, tag_labels=TAG_LABELS)
    return env


_ENV = _env()


def render_html(recap: Recap) -> str:
    """HTML autonome (CSS et captures embarqués), imprimable en A4."""
    days = []
    for d, group in groupby(recap.timeline, key=lambda t: t.start.date()):
        label = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
        if d == recap.race_date:
            label += ", jour de course"
        days.append((label, list(group)))
    generated = recap.generated_at.astimezone(ZoneInfo(recap.calendar_timezone))
    return _ENV.get_template("recap.html.j2").render(
        r=recap, days=days, generated=generated,
        n_calendar=sum(t.in_calendar for t in recap.timeline),
    )


def chrome_path() -> str | None:
    """`RUNAI_CHROME` (ou `CHROME_PATH`) sinon le premier Chrome/Chromium trouvé dans le PATH."""
    for env in ("RUNAI_CHROME", "CHROME_PATH"):
        if os.environ.get(env):
            return os.environ[env]
    for name in CHROME_CANDIDATES:
        if found := shutil.which(name):
            return found
    return None


def html_to_pdf(html: str, chrome: str | None = None) -> bytes:
    """Imprime un HTML en PDF A4 avec Chrome headless (`--print-to-pdf`)."""
    chrome = chrome or chrome_path()
    if not chrome:
        raise PdfRenderError("Chrome/Chromium introuvable : installer Chrome ou définir RUNAI_CHROME.")
    with tempfile.TemporaryDirectory(prefix="runai-recap-") as tmp:
        src, out = Path(tmp) / "recap.html", Path(tmp) / "recap.pdf"
        src.write_text(html, encoding="utf-8")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
               "--disable-extensions", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
               f"--print-to-pdf={out}", src.as_uri()]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=PDF_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PdfRenderError(f"Chrome n'a pas pu générer le PDF : {exc}") from exc
        if not out.exists() or out.stat().st_size == 0:
            tail = proc.stderr.decode(errors="replace")[-500:]
            raise PdfRenderError(f"Chrome n'a pas produit de PDF (code {proc.returncode}) : {tail}")
        return out.read_bytes()


def render_pdf(recap: Recap, chrome: str | None = None) -> bytes:
    """PDF A4 du récap. Bloquant (~0,3-0,6 s) : depuis FastAPI, appeler via `anyio.to_thread.run_sync`."""
    return html_to_pdf(render_html(recap), chrome)
