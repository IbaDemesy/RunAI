import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runai.models import (
    Race,
    RunnerProfile,
    Source,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
)
from runai.recap import (
    PdfRenderError,
    RecapSource,
    TimelineItem,
    default_timeline,
    demo_recap,
    recap_from_mission,
    render_html,
    render_ics,
    render_pdf,
)
from runai.recap import render as render_mod
from runai.recap.build import parse_start_time, race_start
from runai.recap.ics import eu_dst_offsets, fold

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e5274fb00000000049454e44ae426082"
)


def _race(**kw):
    base = {"name": "Milano Marathon", "city": "Milan", "country": "IT", "race_date": date(2027, 4, 4),
                "start_time": "09:00", "distance_km": 42.195, "start_location": "Corso Venezia",
                "sources": [Source(url="https://example.org/milano", title="Site officiel")]}
    return Race(**(base | kw))


def _steps():
    return [
        StepResult(kind=StepKind.search, status=StepStatus.completed),
        StepResult(kind=StepKind.registration, status=StepStatus.stopped_before_commitment,
                   stop_point=StopPoint.consent, url="https://example.org/inscription", price_eur=75.0,
                   summary="Formulaire pré-rempli."),
        StepResult(kind=StepKind.accommodation, status=StepStatus.stopped_before_commitment,
                   stop_point=StopPoint.payment, url="https://example.org/hotel/pay", price_eur=180.0),
        StepResult(kind=StepKind.transport, status=StepStatus.failed, error="captcha"),
    ]


def _unfold(ics: bytes) -> list[str]:
    return ics.decode().replace("\r\n ", "").split("\r\n")


def test_recap_from_mission_defaults():
    r = recap_from_mission(_race(), RunnerProfile(), _steps(), recap_id="m1",
                           generated_at=datetime(2026, 11, 7, 12, tzinfo=UTC))
    assert [m.kind for m in r.missions] == [StepKind.registration, StepKind.accommodation, StepKind.transport]
    assert r.total_eur == 255.0 and r.paid_by_runai_eur == 0 and r.payments_to_do == 2 and r.ready_count == 2
    assert r.runner_fictive and r.runner_name == "Camille Test"
    assert "cochez" not in r.missions[0].human_action and "règlement" in r.missions[0].human_action
    assert "bloqué" in r.missions[2].human_action
    assert [s.found_by for s in r.sources] == ["Linkup", "Agent H", "Agent H"]
    titles = [t.title for t in r.timeline]
    assert titles == ["Retrait du dossard (jour à confirmer)", "Départ : Milano Marathon"]
    start = r.timeline[1].start
    assert start == datetime(2027, 4, 4, 9, tzinfo=ZoneInfo("Europe/Rome")) and r.timeline[1].alarm_minutes
    assert r.timeline[0].time_known is False


def test_recap_from_mission_overrides():
    extra = TimelineItem(start=datetime(2027, 4, 3, 15, tzinfo=ZoneInfo("Europe/Rome")), title="Check-in", tag="a_payer")
    r = recap_from_mission(
        _race(), RunnerProfile(), _steps(),
        prices={StepKind.accommodation: 210.5},
        options={StepKind.accommodation: ["Petit-déjeuner"]},
        extra_timeline=[extra],
        checklist=["Prendre une pièce d'identité"],
        captures={StepKind.registration: PNG_1PX},
    )
    hotel = r.missions[1]
    assert hotel.price_eur == 210.5 and any(f.value == "Petit-déjeuner" for f in hotel.fields)
    assert r.missions[0].capture_data_uri.startswith("data:image/png;base64,")
    assert [t.title for t in r.timeline][1] == "Check-in"
    assert recap_from_mission(_race(), RunnerProfile(), [], timeline=[]).timeline == []


def test_last_step_of_each_kind_wins():
    steps = [StepResult(kind=StepKind.transport, status=StepStatus.failed),
             StepResult(kind=StepKind.transport, status=StepStatus.stopped_before_commitment, stop_point=StopPoint.payment)]
    (m,) = recap_from_mission(_race(), RunnerProfile(), steps).missions
    assert m.status is StepStatus.stopped_before_commitment


@pytest.mark.parametrize(("raw", "expected"), [("09:00", (9, 0)), ("9h30", (9, 30)), ("8 h", (8, 0)), ("à confirmer", None), (None, None)])
def test_parse_start_time(raw, expected):
    t = parse_start_time(raw)
    assert (None if t is None else (t.hour, t.minute)) == expected


def test_race_without_time_gives_all_day_event():
    assert race_start(_race(start_time=None)) is None
    r = recap_from_mission(_race(start_time=None), RunnerProfile(), [])
    assert all(not t.time_known for t in r.timeline)
    lines = _unfold(render_ics(r))
    assert "DTSTART;VALUE=DATE:20270404" in lines and "DTEND;VALUE=DATE:20270405" in lines


def test_html_content_and_vocabulary():
    html = render_html(demo_recap())
    assert "0 € payé par RunAI" in html
    assert "Ce qui reste à faire par toi" in html and "Sources et traçabilité" in html
    assert "https://in.njuko.com/wizz-air-milano-marathon-20271776152378557" in html
    assert "114,00 €" in html and "≈ 492 €" in html
    lower = html.lower()
    assert "réservé" not in lower and "confirmé" not in lower


def test_html_escapes_agent_text():
    steps = [StepResult(kind=StepKind.transport, status=StepStatus.stopped_before_commitment,
                        summary="<script>alert(1)</script>")]
    html = render_html(recap_from_mission(_race(), RunnerProfile(), steps))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_html_embeds_capture():
    r = recap_from_mission(_race(), RunnerProfile(), _steps(), captures={StepKind.registration: PNG_1PX})
    html = render_html(r)
    assert 'src="data:image/png;base64,' in html and "AGENT ARRÊTÉ ICI" in html


def test_ics_rfc5545_structure():
    ics = render_ics(demo_recap())
    text = ics.decode()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert max(len(line.encode()) for line in text.split("\r\n")) <= 75
    lines = _unfold(ics)
    assert lines.count("BEGIN:VTIMEZONE") == 1 and "TZID:Europe/Paris" in lines
    uids = [line for line in lines if line.startswith("UID:")]
    assert len(uids) == len(set(uids)) == 5 == lines.count("BEGIN:VEVENT")
    dtstarts = [line for line in lines if line.startswith("DTSTART;")]
    assert all(d.startswith("DTSTART;TZID=Europe/Paris:") for d in dtstarts)
    assert "DTSTART;TZID=Europe/Paris:20270404T080000" in dtstarts
    assert "TRIGGER:-PT720M" in lines and "TRIGGER:-PT120M" in lines
    assert any("0 € payé par RunAI" in line for line in lines if line.startswith("DESCRIPTION:"))


def test_ics_converts_other_timezones_and_escapes():
    lisbon = ZoneInfo("Europe/Lisbon")
    item = TimelineItem(start=datetime(2027, 3, 7, 9, 30, tzinfo=lisbon), title="Départ, semi; Lisbonne",
                        detail="ligne 1\nligne 2")
    r = recap_from_mission(_race(), RunnerProfile(), [], timeline=[item])
    lines = _unfold(render_ics(r))
    assert "DTSTART;TZID=Europe/Paris:20270307T103000" in lines
    assert "SUMMARY:Départ\\, semi\\; Lisbonne" in lines
    desc = next(line for line in lines if line.startswith("DESCRIPTION:"))
    assert "ligne 1\\nligne 2" in desc and "Heure locale : 09:30 (Europe/Lisbon)" in desc


def test_ics_lisbon_calendar_vtimezone():
    r = recap_from_mission(_race(), RunnerProfile(), [], calendar_timezone="Europe/Lisbon")
    lines = _unfold(render_ics(r))
    assert "TZOFFSETTO:+0100" in lines and "DTSTART:19960331T010000" in lines
    assert "DTSTART;TZID=Europe/Lisbon:20270404T080000" in lines


def test_ics_non_eu_timezone_falls_back_to_utc():
    r = recap_from_mission(_race(), RunnerProfile(), [], calendar_timezone="America/New_York")
    lines = _unfold(render_ics(r))
    assert "BEGIN:VTIMEZONE" not in lines and "DTSTART:20270404T070000Z" in lines


def test_eu_dst_offsets():
    assert eu_dst_offsets("Europe/Paris", 2027) == (timedelta(hours=1), timedelta(hours=2))
    assert eu_dst_offsets("Europe/London", 2027) == (timedelta(0), timedelta(hours=1))
    assert eu_dst_offsets("America/New_York", 2027) is None
    assert eu_dst_offsets("UTC", 2027) is None


def test_fold_keeps_utf8_characters_whole():
    line = "DESCRIPTION:" + "é€" * 60
    folded = fold(line)
    parts = folded.encode().split(b"\r\n")
    assert all(len(p) <= 75 for p in parts)
    assert folded.replace("\r\n ", "") == line


def test_render_pdf_without_chrome(monkeypatch):
    monkeypatch.setattr(render_mod, "chrome_path", lambda: None)
    with pytest.raises(PdfRenderError):
        render_pdf(demo_recap())


def test_render_pdf_calls_chrome_headless(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1]
        with open(out, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    assert render_pdf(demo_recap(), chrome="/usr/bin/fake-chrome") == b"%PDF-1.4 fake"
    assert seen["cmd"][0] == "/usr/bin/fake-chrome" and "--headless=new" in seen["cmd"]
    assert seen["cmd"][-1].startswith("file://")


def test_render_pdf_reports_chrome_failure(monkeypatch):
    monkeypatch.setattr(render_mod.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"boom"))
    with pytest.raises(PdfRenderError, match="boom"):
        render_pdf(demo_recap(), chrome="/usr/bin/fake-chrome")


@pytest.mark.skipif(render_mod.chrome_path() is None, reason="Chrome/Chromium absent")
def test_render_pdf_real_chrome():
    pdf = render_pdf(demo_recap())
    assert pdf.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) >= 2


def test_non_http_urls_rejected():
    with pytest.raises(ValueError):
        RecapSource(label="x", url="javascript:alert(1)")
    assert RecapSource(label="x", url="https://example.com").url == "https://example.com"


def test_invalid_minutes_and_unknown_country_keep_time_as_text():
    assert parse_start_time("09:75") is None
    race = _race(country="US", start_time="07:30")
    assert race_start(race) is None
    course = next(t for t in default_timeline(race) if t.tag == "course")
    assert not course.time_known and "07:30" in course.detail
    assert course.start.date() == race.race_date


def test_default_notice_depends_on_profile():
    fake = recap_from_mission(_race(), RunnerProfile(), [])
    real = recap_from_mission(_race(), RunnerProfile(email="vrai@coureur.fr"), [])
    assert "fictif" in fake.notice and "fictif" not in real.notice
    assert "Rien n'a été payé" in real.notice
