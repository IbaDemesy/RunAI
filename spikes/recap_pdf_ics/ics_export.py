"""Recap -> .ics (RFC 5545). Tous les DTSTART/DTEND en TZID=Europe/Paris avec VTIMEZONE embarque."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event

from models import Recap

DEFAULT_DURATION = timedelta(minutes=30)

# VTIMEZONE compacte (regle UE depuis 1996) plutot que les RDATE 1970-2038 generees par icalendar.
PARIS_VTIMEZONE = (
    "BEGIN:VTIMEZONE\r\nTZID:Europe/Paris\r\n"
    "BEGIN:DAYLIGHT\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\nTZNAME:CEST\r\n"
    "DTSTART:19960331T020000\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\nEND:DAYLIGHT\r\n"
    "BEGIN:STANDARD\r\nTZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nTZNAME:CET\r\n"
    "DTSTART:19961027T030000\r\nRRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\nEND:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
)


def build_ics(r: Recap) -> bytes:
    tz = ZoneInfo(r.timezone)
    cal = Calendar()
    cal.add("prodid", "-//RunAI//recap week-end//FR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"RunAI · {r.race_name}")
    cal.add("x-wr-timezone", r.timezone)
    stamp = r.generated_at.astimezone(timezone.utc)
    links = {m.key: m.finalize_url for m in r.missions if m.finalize_url}
    for i, it in enumerate(sorted((t for t in r.timeline if t.in_calendar), key=lambda t: t.start)):
        start = it.start.astimezone(tz)
        end = (it.end or it.start + DEFAULT_DURATION).astimezone(tz)
        ev = Event()
        ev.add("uid", f"{r.id}-{i:02d}@runai.local")
        ev.add("dtstamp", stamp)
        ev.add("dtstart", start)
        ev.add("dtend", end)
        ev.add("summary", it.title)
        desc = [it.detail or ""]
        if it.start.tzinfo and str(it.start.tzinfo) != r.timezone:
            desc.append(f"Heure locale : {it.start:%H:%M} ({it.start.tzinfo}).")
        if it.tag == "a_payer":
            desc.append("Statut : prêt, à payer (rien n'est payé par RunAI).")
            url = links.get(it.mission_key) if getattr(it, "mission_key", None) else None
            if url:
                desc.append(f"Finaliser : {url}")
        ev.add("description", "\n".join(d for d in desc if d))
        if it.location:
            ev.add("location", it.location)
        ev.add("categories", ["RunAI", it.tag])
        ev.add("transp", "OPAQUE")
        if it.tag in ("inscription_prete",) or "dossard" in it.title.lower():
            al = Alarm()
            al.add("action", "DISPLAY")
            al.add("description", it.title)
            al.add("trigger", timedelta(hours=-12 if "dossard" not in it.title.lower() else -2))
            ev.add_component(al)
        cal.add_component(ev)
    if r.timezone == "Europe/Paris":
        cal.subcomponents.insert(0, Calendar.from_ical(PARIS_VTIMEZONE))
    else:
        cal.add_missing_timezones()
    return cal.to_ical()


def validate_ics(data: bytes) -> dict:
    """Relit le fichier avec icalendar ET vobject (2 parseurs independants) + controles RFC 5545."""
    import vobject

    text = data.decode("utf-8")
    cal = Calendar.from_ical(data)
    events = cal.walk("VEVENT")
    tzids = sorted({str(e["DTSTART"].params.get("TZID")) for e in events})
    v = vobject.readOne(text)
    v.validate()
    lines = text.split("\r\n")
    return {
        "events": len(events),
        "vtimezone": [str(t["TZID"]) for t in cal.walk("VTIMEZONE")],
        "dtstart_tzids": tzids,
        "crlf_only": "\n" not in text.replace("\r\n", ""),
        "max_line_octets": max(len(l.encode()) for l in lines),
        "vobject_events": len(v.contents.get("vevent", [])),
        "uids_unique": len({str(e["UID"]) for e in events}) == len(events),
        "summaries": [str(e["SUMMARY"]) for e in events],
    }
