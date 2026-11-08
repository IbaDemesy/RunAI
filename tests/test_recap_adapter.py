from datetime import UTC, date, datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import pytest

from runai.contracts import load_fixture
from runai.contracts.common import DataMode
from runai.contracts.framing import FramingSummary
from runai.contracts.journey import Budget, JourneyPlan
from runai.journey import JourneyInputs, Place, RaceDetails, build_journey_plan
from runai.models import Race
from runai.planning.recap_adapter import (
    recap_from_journey,
    render_html,
    render_ics,
    render_pdf,
)
from runai.recap.render import chrome_path


def fixture(name):
    return JourneyPlan.model_validate(load_fixture(f"journey_{name}.json"))


def tokyo_plan():
    return build_journey_plan(
        FramingSummary(revision=2, race=Race(name="Tokyo run", city="Tokyo", country="JP",
                                            race_date=date(2030, 3, 3), distance_km=10),
                       origin_public="Montréal", date_range=(date(2030, 3, 1), date(2030, 3, 5)),
                       nights=4, lines=[], budget_eur=None, transport_mode="flight"),
        JourneyInputs(home=Place(label="18 rue privée, H2X Montréal", timezone="America/Toronto"),
                      race=RaceDetails(start=Place(label="Tokyo start", timezone="Asia/Tokyo"),
                                       start_time=datetime(2030, 3, 3, 9, 15, tzinfo=ZoneInfo("Asia/Tokyo")))),
        mission_id="tokyo", mode=DataMode.demo,
    )


def unfolded(snapshot):
    return render_ics(snapshot).decode().replace("\r\n ", "")


def calendar_starts(text):
    starts = []
    for event in text.split("BEGIN:VEVENT")[1:]:
        line = next(line for line in event.split("\r\n") if line.startswith("DTSTART"))
        prop, value = line.split(":", 1)
        if "TZID=" in prop:
            starts.append(datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(prop.split("TZID=")[1])).astimezone(UTC))
        else:
            starts.append(datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return sorted(starts)


@pytest.mark.parametrize("value", ["x\rBEGIN:VEVENT", "x\r\nBEGIN:VEVENT", "x\nBEGIN:VEVENT"])
def test_j2_ics_escapers_remove_every_line_break(value):
    from runai.logistics.ics import _escape
    from runai.recap.ics import escape_text

    for escape in (escape_text, _escape):
        assert escape(value) == "x\\nBEGIN:VEVENT"


def test_j2_calendar_metadata_only_inserted_at_final_terminator():
    plan = tokyo_plan()
    next(s for s in plan.stops if s.id == "start").label = "END:VCALENDAR; injected\rBEGIN:VEVENT"
    text = unfolded(recap_from_journey(plan))
    assert text.count("X-RUNAI-SCHEMA:") == 1
    assert "\r" not in text.replace("\r\n", "")
    assert text.endswith("END:VCALENDAR\r\n")


def test_j8_integral_budget_is_formatted_without_decimal_suffix():
    plan = tokyo_plan()
    plan.budget.cap = 800
    snapshot = recap_from_journey(plan)
    html = unescape(render_html(snapshot))
    assert "€800" in html
    assert "800.0" not in html


def test_j9_recap_uses_race_identity_not_mission_id():
    recap = recap_from_journey(tokyo_plan()).recap
    assert recap.race_name == "Tokyo run"
    assert recap.runner_name != "you"


def test_j9_calendar_uids_survive_event_insertion_and_revision():
    plan = tokyo_plan()

    def events(text):
        result = {}
        for event in text.split("BEGIN:VEVENT")[1:]:
            fields = dict(line.split(":", 1) for line in event.split("\r\n") if ":" in line)
            result[(fields["DTSTART"], fields["SUMMARY"])] = fields
        return result

    original = events(unfolded(recap_from_journey(plan)))
    home = next(stop for stop in plan.stops if stop.kind.value == "home")
    home.local_time = datetime(2030, 3, 1, tzinfo=UTC)
    plan.revision += 1
    revised = events(unfolded(recap_from_journey(plan)))
    assert len(revised) == len(original) + 1
    for key, event in original.items():
        assert revised[key]["UID"] == event["UID"]
        assert revised[key]["SEQUENCE"] == str(plan.revision)
    assert len({event["UID"] for event in revised.values()}) == len(revised)
    home.local_time -= timedelta(hours=1)
    changed = events(unfolded(recap_from_journey(plan)))
    assert {event["UID"] for event in revised.values()} != {event["UID"] for event in changed.values()}


@pytest.mark.parametrize("factory", [lambda: fixture("train"), lambda: fixture("flight"),
                                     lambda: fixture("incomplete"), tokyo_plan])
def test_plan_exports(factory):
    plan = factory()
    snapshot = recap_from_journey(plan)
    html, ics = unescape(render_html(snapshot)), unfolded(snapshot)
    assert snapshot == recap_from_journey(plan)
    assert render_html(snapshot) == render_html(recap_from_journey(plan))
    assert render_ics(snapshot) == render_ics(recap_from_journey(plan))
    assert snapshot.revision == plan.revision
    assert snapshot.mission_id == plan.mission_id
    assert snapshot.mode == plan.mode.value
    assert f"revision {plan.revision}" in html
    assert f"X-RUNAI-REVISION:{plan.revision}" in ics
    assert "Prepared ≠ booked" in html and "Prepared ≠ booked" in ics
    assert "not live data" in html and "not live data" in ics
    expected = []
    stops = {s.id: s for s in plan.stops}
    times = [(s.local_time, s.timezone) for s in plan.stops]
    times += [(s.departure, stops[s.from_stop_id].timezone or s.timezone) for s in plan.segments]
    times += [(s.arrival, stops[s.to_stop_id].timezone or s.timezone) for s in plan.segments]
    for value, tz in times:
        if value is None:
            continue
        local = value.astimezone(ZoneInfo(tz)) if tz else value
        expected.append(local.astimezone(UTC))
        assert local.isoformat() in html and local.isoformat() in ics
        if tz:
            assert tz in html and tz in ics
    assert calendar_starts(ics) == sorted(expected)
    assert "DTEND" not in ics
    for line in plan.budget.lines:
        if line.money:
            amount = f"{line.money.amount:,.2f}".rstrip("0").rstrip(".")
            value = f"€{amount}" if line.money.currency == "EUR" else f"{amount} {line.money.currency}"
        else:
            value = "not priced"
        assert value in html and value in ics
    total = f"{plan.budget.known_total:,.2f}".rstrip("0").rstrip(".")
    assert (f"€{total}" if plan.budget.currency == "EUR" else f"{total} {plan.budget.currency}") in html
    if not plan.budget.complete:
        assert "Known total (partial)" in html and "Known total (partial)" in ics
    if plan.budget.over_cap is None:
        assert "unknown" in html and "unknown" in ics
    for segment in plan.segments:
        if segment.automation.value in ("manual", "not_covered"):
            assert "not automated" in html and "not automated" in ics
            if segment.manual_url:
                assert segment.manual_url in html and segment.manual_url in ics
    for limitation in plan.limitations:
        assert limitation.message in html and limitation.message in ics
    assert "estimated total, for you to pay" not in html
    assert "18 rue privée" not in html + ics


def test_masked_home_and_snapshot_isolation():
    plan = fixture("flight")
    home = next(s for s in plan.stops if s.kind.value == "home")
    home.label = "12 rue de la Roquette, 75011 Paris"
    snapshot = recap_from_journey(plan)
    before = render_html(snapshot), render_ics(snapshot)
    assert "Roquette" not in before[0] + before[1].decode()
    assert "75011" not in before[0] + before[1].decode()
    plan.revision += 1
    snapshot.recap.key_facts.clear()
    assert before == (render_html(snapshot), render_ics(snapshot))


def test_empty_unknown_and_replay():
    plan = fixture("incomplete")
    plan.stops = []
    plan.segments = []
    plan.chapters = []
    plan.budget = Budget(currency=plan.currency)
    plan.mode = DataMode.replay
    snapshot = recap_from_journey(plan)
    html, ics = render_html(snapshot), unfolded(snapshot)
    assert calendar_starts(ics) == []
    assert "REPLAY" in html and "REPLAY" in ics
    assert "unknown" in html and "Known total (partial)" in html
    assert "DTSTART" not in ics


def test_invalid_manual_url_rejected():
    plan = fixture("train")
    plan.segments[0].manual_url = "javascript:alert(1)"
    with pytest.raises(ValueError, match="http"):
        recap_from_journey(plan)


def test_segment_currency_not_added_to_budget():
    plan = fixture("train")
    segment = next(s for s in plan.segments if s.cost)
    segment.cost.currency = "USD"
    segment.cost.amount = 987.65
    snapshot = recap_from_journey(plan)
    html, ics = render_html(snapshot), unfolded(snapshot)
    assert "987.65 USD" in html and "987.65 USD" in ics
    assert "€503" in html
    assert f"{plan.budget.known_total + 987.65} {plan.currency}" not in html


def test_unknown_timezone_is_not_invented():
    plan = fixture("incomplete")
    stop = plan.stops[-1]
    stop.local_time = datetime(2031, 4, 5, 8, 23)
    stop.timezone = None
    snapshot = recap_from_journey(plan)
    assert "2031-04-05T08:23:00 (unknown timezone)" in render_html(snapshot)
    assert calendar_starts(unfolded(snapshot)) == []


def test_pdf():
    if not chrome_path():
        pytest.skip("Chrome/Chromium unavailable: existing recap PDF renderer requires Chrome, not WeasyPrint")
    assert render_pdf(recap_from_journey(tokyo_plan())).startswith(b"%PDF-")
