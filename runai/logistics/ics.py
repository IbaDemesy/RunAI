"""Export iCalendar (RFC 5545) d'une `Timeline`, heures en UTC pour éviter tout VTIMEZONE."""

import hashlib
from datetime import UTC, datetime

from runai.logistics.models import Timeline

_FORMAT = "%Y%m%dT%H%M%SZ"


def to_ics(timeline: Timeline, *, now: datetime | None = None) -> str:
    """Un VEVENT par événement ; « (estimé) » dans le titre quand l'horaire vient d'une hypothèse."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime(_FORMAT)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RunAI//logistics//FR",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(timeline.race_name)}",
        f"X-WR-TIMEZONE:{timeline.timezone}",
    ]
    for event in timeline.events:
        start = event.start.astimezone(UTC)
        uid = hashlib.sha1(f"{event.title}|{start.isoformat()}".encode()).hexdigest()[:16]
        summary = event.title + (" (estimé)" if event.assumption else "")
        description = "\n".join(part for part in (event.detail, f"Source : {event.source_url}" if event.source_url else None) if part)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@runai",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.strftime(_FORMAT)}",
            f"DTEND:{event.end.astimezone(UTC).strftime(_FORMAT)}",
            f"SUMMARY:{_escape(summary)}",
        ]
        if description:
            lines.append(f"DESCRIPTION:{_escape(description)}")
        if event.location:
            lines.append(f"LOCATION:{_escape(event.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str, limit: int = 75) -> str:
    parts, current, size = [], "", 0
    for char in line:
        width = len(char.encode())
        if size + width > limit:
            parts.append(current)
            current, size, limit = " ", 1, 75
        current += char
        size += width
    parts.append(current)
    return "\r\n".join(parts)
