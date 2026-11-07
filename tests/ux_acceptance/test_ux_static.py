"""Static review only: patterns document the D1/C3 shell contract."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from . import checks

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "runai/app/static"
HERE = Path(__file__).parent
DEFECTS = [
    ("UX-01", "app.js", "equivalent focus or h1 after render and mutation", "major"),
    ("UX-02", "app.js", "aria-current=page on current navigation", "medium"),
    ("UX-03", "app.js", "names contextualized by candidate/question", "medium"),
    ("UX-04", "app.js", "announce mission.status changes via SSE", "medium"),
    ("UX-05", "app.js", "region role on journey-map", "minor"),
    ("UX-06", "app.js", "single h1 and no skipped heading levels", "minor"),
    ("UX-07", "app.js", "new tab in the accessible name", "minor"),
    ("UX-08", "app.js", "Play absent with reduced motion", "minor"),
    ("UX-09", "live.html", "viewport and announced live status", "minor"),
]


def read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def run(*args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_d1_regressions():
    assert checks.html_basics(read("index.html")) == []
    assert checks.labelled_fields(read("app.js")) == []
    assert checks.css_accessibility(read("style.css")) == []
    assert checks.external_links(read("app.js")) == []
    assert checks.reduced_motion_option(read("app.js")) == []


@pytest.mark.parametrize("identifier,filename,expected,severity", DEFECTS, ids=[r[0] for r in DEFECTS])
def test_known_d1_defect_fixed(identifier, filename, expected, severity):
    assert checks.defect(read(filename), identifier) == []


def test_palette_contrasts():
    assert checks.contrasts(read("style.css")) == []


def test_other_palette_contrasts():
    errors = checks.contrasts(read("style.css"))
    assert all(error.startswith(("ink-3/paper:", "ink-3/paper-2:")) for error in errors), errors


@pytest.fixture(scope="module")
def patched(tmp_path_factory):
    directory = tmp_path_factory.mktemp("d1-patched")
    target = directory / "runai/app/static"
    target.mkdir(parents=True)
    for name in ("app.js", "live.html", "style.css"):
        # Patches remain replayable against the reviewed D1 base (97265c6).
        source = run("git", "show", f"97265c6:runai/app/static/{name}", cwd=ROOT)
        (target / name).write_text(source, encoding="utf-8")
    for patch in sorted((HERE / "fixes").glob("d1-*.patch")):
        run("git", "apply", "--check", str(patch), cwd=directory)
        run("git", "apply", str(patch), cwd=directory)
    assert shutil.which("node"), "Load Node: source ~/.nvm/nvm.sh"
    run("node", "--check", str(target / "app.js"), cwd=directory)
    return target


@pytest.mark.parametrize("identifier,filename,expected,severity", DEFECTS, ids=[r[0] for r in DEFECTS])
def test_corrective_patch(patched, identifier, filename, expected, severity):
    assert checks.defect((patched / filename).read_text(), identifier, legacy=True) == []


def test_corrected_palette(patched):
    assert checks.contrasts((patched / "style.css").read_text()) == []


def test_patches_preserve_regressions(patched):
    app = (patched / "app.js").read_text()
    assert checks.labelled_fields(app) == []
    assert checks.external_links(app) == []
    assert checks.reduced_motion_option(app) == []
    assert checks.css_accessibility((patched / "style.css").read_text()) == []
    assert checks.html_basics((patched / "live.html").read_text(), feedback=False, lang="fr") == []


def test_c3_contracts():
    configured = os.environ.get("RUNAI_UX_C3_DIR")
    directory = Path(configured) if configured else ROOT / "web/flyover"
    if not configured and not (directory / "journey-fallback.js").exists():
        pytest.skip("C3 not integrated yet: E3 wiring; provide RUNAI_UX_C3_DIR")
    source = (directory / "journey-fallback.js").read_text()
    assert checks.c3_accessibility(source) == []
    assert checks.external_links(source) == []
    assert checks.css_accessibility((directory / "journey.css").read_text()) == []


@pytest.mark.parametrize("check", [checks.html_basics, checks.css_accessibility, checks.external_links, checks.reduced_motion_option, checks.contrasts, checks.c3_accessibility])
def test_missing_and_invalid_source(check):
    assert check("")
    assert check("invalid source")


def test_labelled_fields_negative_and_empty():
    assert checks.labelled_fields("") == []
    assert checks.labelled_fields('const input = el("input");')
    assert checks.labelled_fields('const input = el("input"); fieldLabel.append(input);') == []


@pytest.mark.parametrize("identifier", [row[0] for row in DEFECTS])
def test_defect_checks_reject_missing_source(identifier):
    assert checks.defect("", identifier)
    assert checks.defect("invalid source", identifier)


def test_wcag_reference_values():
    assert checks.contrast_ratio("#000", "#fff") == 21
    assert checks.contrast_ratio("#fff", "#ffffff") == 1
    assert checks.contrast_ratio("#777", "#fff") < 4.5
