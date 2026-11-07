"""Recap -> HTML (Jinja2) -> PDF. Trois moteurs comparables: playwright, chrome_cli, weasyprint."""

import base64
import os
import shutil
import subprocess
import tempfile
from glob import glob
from itertools import groupby
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from models import Recap
from svg_profile import elevation_gain, render_profile_svg

HERE = Path(__file__).parent
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
TAG_LABELS = {"a_payer": "à payer", "info": "info", "conseil": "conseil", "inscription_prete": "inscription prête"}
STATUS_LABELS = {"pret_a_payer": "prêt, à payer", "en_cours": "en cours", "bloque": "bloqué", "non_lance": "non lancé"}


def _eur(v: float, dec: int = 2) -> str:
    return f"{v:,.{dec}f}".replace(",", " ").replace(".", ",") + " €"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(
        date_long=lambda d: f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}",
        dt_short=lambda d: f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year} à {d:%H:%M}",
        hm=lambda d: f"{d:%H:%M}",
        hms=lambda d: f"{d:%H:%M:%S}",
        eur=_eur,
        eur0=lambda v: _eur(v, 0),
        duration=lambda s: f"{s // 60} min {s % 60:02d} s" if s else "",
    )
    return env


ENV = _env()


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def render_html(r: Recap) -> str:
    items = sorted(r.timeline, key=lambda t: t.start)
    days = []
    for d, group in groupby(items, key=lambda t: t.start.date()):
        label = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
        if d == r.race_date:
            label += ", jour de course"
        days.append((label, list(group)))
    images = {m.key: _data_uri(HERE / m.capture.image_path) for m in r.missions if m.capture.image_path}
    return ENV.get_template("recap.html.j2").render(
        r=r, days=days, images=images,
        n_cal=sum(t.in_calendar for t in r.timeline),
        tag_labels=TAG_LABELS, status_labels=STATUS_LABELS,
        profile_svg=render_profile_svg(r.profile) if r.profile else "",
        dplus=str(elevation_gain(r.profile)) if r.profile else "?",
    )


def chrome_path() -> str:
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    for cand in sorted(glob("/opt/.devin/chrome/chrome/linux-*/chrome-linux64/chrome")) + [
        shutil.which("google-chrome-stable") or "", shutil.which("chromium") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]:
        if cand and Path(cand).exists():
            return cand
    return ""


PDF_OPTS = dict(format="A4", print_background=True, prefer_css_page_size=True)


async def pdf_playwright_async(html: str, browser=None) -> bytes:
    """Utilise un navigateur deja lance (cas serveur) ou en lance un."""
    if browser is not None:
        page = await browser.new_page()
        try:
            await page.set_content(html, wait_until="load")
            return await page.pdf(**PDF_OPTS)
        finally:
            await page.close()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chrome_path() or None)
        try:
            return await pdf_playwright_async(html, b)
        finally:
            await b.close()


def pdf_playwright(html: str) -> bytes:
    import asyncio

    return asyncio.run(pdf_playwright_async(html))


def pdf_chrome_cli(html: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "recap.html", Path(d) / "recap.pdf"
        src.write_text(html, encoding="utf-8")
        subprocess.run(
            [chrome_path(), "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
             f"--user-data-dir={d}/profile", f"--print-to-pdf={out}", src.as_uri()],
            check=True, capture_output=True, timeout=60,
        )
        return out.read_bytes()


def pdf_weasyprint(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=str(HERE)).write_pdf()


ENGINES = {"playwright": pdf_playwright, "chrome_cli": pdf_chrome_cli, "weasyprint": pdf_weasyprint}
