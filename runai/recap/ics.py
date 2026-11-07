"""Recap → .ics (RFC 5545), sans dépendance : CRLF, lignes pliées à 75 octets, TZID + VTIMEZONE."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Recap, TimelineItem

PRODID = "-//RunAI//Recap week-end//FR"
DEFAULT_DURATION = timedelta(minutes=30)


def escape_text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Plie une ligne de contenu à 75 octets sans couper un caractère UTF-8 (RFC 5545 §3.1)."""
    out, cur, size, limit = [], [], 0, 75
    for ch in line:
        n = len(ch.encode())
        if size + n > limit:
            out.append("".join(cur))
            cur, size, limit = [" "], 1, 75
        cur.append(ch)
        size += n
    out.append("".join(cur))
    return "\r\n".join(out)


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def eu_dst_offsets(tzname: str, year: int) -> tuple[timedelta, timedelta] | None:
    """(décalage hiver, décalage été) si le fuseau suit la règle UE (changement à 01:00 UTC
    les derniers dimanches de mars et d'octobre) pour `year`, sinon None."""
    tz = ZoneInfo(tzname)
    std = datetime(year, 1, 15, tzinfo=tz).utcoffset()
    dst = datetime(year, 7, 15, tzinfo=tz).utcoffset()
    if std is None or dst is None or std == dst:
        return None
    for month, before, after in ((3, std, dst), (10, dst, std)):
        switch = datetime.combine(_last_sunday(year, month), datetime.min.time(), tzinfo=UTC) + timedelta(hours=1)
        if (switch - timedelta(minutes=1)).astimezone(tz).utcoffset() != before or switch.astimezone(tz).utcoffset() != after:
            return None
    return std, dst


def _offset(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}"


def vtimezone(tzname: str, std: timedelta, dst: timedelta) -> list[str]:
    """VTIMEZONE compacte à règle UE (RRULE annuelle) plutôt qu'une liste de RDATE."""
    tz = ZoneInfo(tzname)
    names = (datetime(2001, 1, 15, tzinfo=tz).tzname(), datetime(2001, 7, 15, tzinfo=tz).tzname())
    spring = (datetime(1996, 3, 31, 1) + std).strftime("%Y%m%dT%H%M%S")
    autumn = (datetime(1996, 10, 27, 1) + dst).strftime("%Y%m%dT%H%M%S")
    return [
        "BEGIN:VTIMEZONE", f"TZID:{tzname}",
        "BEGIN:DAYLIGHT", f"TZOFFSETFROM:{_offset(std)}", f"TZOFFSETTO:{_offset(dst)}", f"TZNAME:{names[1]}",
        f"DTSTART:{spring}", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
        "BEGIN:STANDARD", f"TZOFFSETFROM:{_offset(dst)}", f"TZOFFSETTO:{_offset(std)}", f"TZNAME:{names[0]}",
        f"DTSTART:{autumn}", "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
        "END:VTIMEZONE",
    ]


def _description(item: TimelineItem, local: datetime) -> str:
    parts = [item.detail or ""]
    if item.time_known and item.start.utcoffset() != local.utcoffset():
        parts.append(f"Heure locale : {item.start:%H:%M} ({item.start.tzinfo}).")
    if item.tag == "a_payer":
        parts.append("Statut : prêt, à payer par toi (0 € payé par RunAI).")
    parts.append("Préparé par RunAI.")
    return "\n".join(p for p in parts if p)


def render_ics(recap: Recap) -> bytes:
    """Événements de la timeline marqués `in_calendar`, en heure de `recap.calendar_timezone`.

    Si ce fuseau ne suit pas la règle UE, les heures sont écrites en UTC (suffixe Z).
    """
    items = [t for t in recap.timeline if t.in_calendar]
    tzname = recap.calendar_timezone
    tz = ZoneInfo(tzname)
    years = {t.start.year for t in items} or {recap.generated_at.year}
    rules = {eu_dst_offsets(tzname, y) for y in years}
    rule = rules.pop() if len(rules) == 1 else None
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{escape_text('RunAI · ' + recap.race_name)}"]
    if rule:
        lines += [f"X-WR-TIMEZONE:{tzname}", *vtimezone(tzname, *rule)]
    stamp = recap.generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    def dt(prop: str, value: datetime) -> str:
        if rule:
            return f"{prop};TZID={tzname}:{value.astimezone(tz):%Y%m%dT%H%M%S}"
        return f"{prop}:{value.astimezone(UTC):%Y%m%dT%H%M%SZ}"

    for i, item in enumerate(sorted(items, key=lambda t: t.start)):
        local = item.start.astimezone(tz)
        lines += ["BEGIN:VEVENT", f"UID:{recap.id}-{i:02d}@runai", f"DTSTAMP:{stamp}"]
        if item.time_known:
            lines += [dt("DTSTART", item.start), dt("DTEND", item.end or item.start + DEFAULT_DURATION)]
        else:
            day = item.start.date()
            lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
        lines += [f"SUMMARY:{escape_text(item.title)}", f"DESCRIPTION:{escape_text(_description(item, local))}"]
        if item.location:
            lines.append(f"LOCATION:{escape_text(item.location)}")
        lines += [f"CATEGORIES:RunAI,{item.tag}", "TRANSP:OPAQUE" if item.time_known else "TRANSP:TRANSPARENT"]
        if item.alarm_minutes:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape_text(item.title)}",
                      f"TRIGGER:-PT{item.alarm_minutes}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode()
