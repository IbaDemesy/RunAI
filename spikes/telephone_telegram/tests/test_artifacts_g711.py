import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime

from artifacts import course_gpx, race_ics, recap_pdf
from g711 import pcm16_to_ulaw, resample_pcm16, ulaw_to_pcm16
from orchestrator import MockOrchestrator, parse_request


def mission():
    orch = MockOrchestrator(step_delay=0)
    return asyncio.run(
        orch.start_mission("Trouve-moi un semi en avril", "telegram", "1")
    )


def test_ics_gpx_pdf():
    m = mission()
    ics = race_ics(m, now=datetime(2026, 11, 7)).decode()
    assert (
        ics.startswith("BEGIN:VCALENDAR\r\n")
        and "DTSTART;TZID=Europe/Paris:20270404T090000" in ics
    )
    assert "DTSTAMP:20261107T000000Z" in ics and ics.endswith("END:VCALENDAR\r\n")
    root = ET.fromstring(course_gpx(m))
    assert len(root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")) == 10
    assert recap_pdf(m).startswith(b"%PDF")


def test_parse_request():
    r = parse_request("Trouve-moi un semi en avril et prépare tout")
    assert (r.distance, r.month, r.complete) == ("semi-marathon", "avril", True)
    assert not parse_request("prépare tout").complete


def test_g711_roundtrip_and_known_values():
    assert pcm16_to_ulaw(b"\x00\x00") == b"\xff"  # silence G.711 mu-law
    pcm = b"".join(
        int(v).to_bytes(2, "little", signed=True)
        for v in (0, 1000, -1000, 32000, -32000)
    )
    back = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    for a, b in zip(memoryview(pcm).cast("h"), memoryview(back).cast("h")):
        assert abs(a - b) <= max(16, abs(a) * 0.04)
    assert len(resample_pcm16(b"\x00\x00" * 24000, 24000, 8000)) == 8000 * 2
