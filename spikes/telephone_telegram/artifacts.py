"""Recap de mission : PDF (fpdf2), .ics (RFC 5545) et GPX 1.1. Donnees de demo fictives."""

from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

from fpdf import FPDF
from orchestrator import AGENT_LABELS, FAKE_RUNNER, Mission


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def recap_pdf(mission: Mission) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(
        0, 12, _latin1(f"RunAI - {mission.race['name']}"), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_font("Helvetica", size=11)
    lines = [
        f"Coureur (fictif) : {FAKE_RUNNER['first_name']} {FAKE_RUNNER['last_name']}",
        f"Date : {mission.race['date']} a {mission.race['start_time']} - {mission.race['city']}",
        f"Demande : {mission.request.raw_text}",
        "",
    ]
    for agent, label in AGENT_LABELS.items():
        decision = mission.decisions.get(agent)
        state = {True: "valide - a payer par toi", False: "refuse"}.get(
            decision, mission.statuses[agent]
        )
        lines.append(f"{label} : {state}")
    lines += [
        "",
        "Rien n'a ete paye ni soumis par RunAI. Tu signes, tu paies, eux jamais.",
    ]
    for line in lines:
        pdf.multi_cell(0, 7, _latin1(line), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def race_ics(mission: Mission, now: datetime | None = None) -> bytes:
    start = datetime.fromisoformat(
        f"{mission.race['date']}T{mission.race['start_time']}"
    )
    end = start + timedelta(hours=3)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")

    def esc(v: str) -> str:
        return (
            v.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n")
        )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RunAI//spike telephone_telegram//FR",
        "BEGIN:VEVENT",
        f"UID:{mission.id}@runai.example",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID=Europe/Paris:{start:%Y%m%dT%H%M%S}",
        f"DTEND;TZID=Europe/Paris:{end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{esc(mission.race['name'])}",
        f"LOCATION:{esc(mission.race['city'])}",
        f"GEO:{mission.race['start_lat']};{mission.race['start_lon']}",
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        "DESCRIPTION:Retrait du dossard",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()


def course_gpx(
    mission: Mission, points: list[tuple[float, float]] | None = None
) -> bytes:
    lat, lon = mission.race["start_lat"], mission.race["start_lon"]
    pts = points or [
        (lat + i * 0.001, lon + i * 0.0015) for i in range(10)
    ]  # trace factice
    body = "".join(f'<trkpt lat="{a:.6f}" lon="{b:.6f}"/>' for a, b in pts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="RunAI spike" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{escape(mission.race['name'])}</name><trkseg>{body}</trkseg></trk></gpx>"
    ).encode()
