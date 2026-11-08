"""Versioned JourneyPlan snapshot, rendered with the existing recap package.

Use the render functions here, not the legacy mission renderers directly: the
legacy template assumes EUR payments and its calendar invents default durations.
The snapshot stores serialized data so callers cannot mutate a later export.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from runai.contracts.journey import JourneyPlan, Money, StopKind
from runai.journey import public_origin
from runai.recap import KeyFact, Recap, RecapSource, TimelineItem
from runai.recap import render_html as legacy_html
from runai.recap import render_ics as legacy_ics
from runai.recap.ics import escape_text, fold
from runai.recap.render import html_to_pdf
from runai.redaction import redact_secrets


@dataclass(frozen=True)
class JourneyRecap:
    """Immutable, deterministic snapshot shared by HTML, PDF and calendar exports."""

    mission_id: str
    revision: int
    mode: str
    schema_version: str
    _recap_json: str

    @property
    def recap(self) -> Recap:
        return Recap.model_validate_json(self._recap_json)


def _amount(value: float, currency: str) -> str:
    amount = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"€{amount}" if currency == "EUR" else f"{amount} {currency}"


def _money(value: Money | None) -> str:
    return _amount(value.amount, value.currency) if value else "not priced"


def _local(value: datetime, timezone: str | None) -> datetime:
    if timezone:
        tz = ZoneInfo(timezone)
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return value


def recap_from_journey(plan: JourneyPlan) -> JourneyRecap:
    """Adapt a journey.v1 plan without inferring schedules, prices or bookings.

    Naive times without a stop/segment timezone remain text-only. Each known
    departure and arrival is a separate calendar point (no inferred duration).
    """
    plan = JourneyPlan.model_validate(redact_secrets(plan.model_dump(mode="json")))
    identity = f"{plan.schema_version} · {plan.mission_id} · revision {plan.revision} · {plan.mode.value}"
    prepared = "Prepared ≠ booked: nothing booked, paid or confirmed."
    mode = {"demo": "DEMO — demonstration data, not live data.",
            "replay": "REPLAY — recorded replay, not live data.",
            "live": "Live mode — preparation only."}[plan.mode.value]
    notice = f"{identity} · {mode} {prepared}"
    facts = [KeyFact(label="Snapshot", value=identity),
             KeyFact(label="Public origin", value=public_origin(plan.origin_public))]
    if plan.date_range:
        facts.append(KeyFact(label="Dates", value=" → ".join(d.isoformat() for d in plan.date_range)))
    budget = plan.budget
    facts.extend([
        KeyFact(label="Known total" + (" (partial)" if not budget.complete else ""),
                value=_amount(budget.known_total, budget.currency)),
        KeyFact(label="Budget cap", value=_amount(budget.cap, budget.currency) if budget.cap is not None else "unknown"),
        KeyFact(label="Over budget cap", value="unknown" if budget.over_cap is None else str(budget.over_cap).lower()),
    ])
    for line in budget.lines:
        facts.append(KeyFact(label=line.label, value=_money(line.money), detail=line.note))
    checklist = list(plan.warnings)
    manual_sources = []
    timeline = []
    stamps = []

    def point(title: str, value: datetime | None, timezone: str | None, detail: str, calendar_id: str) -> None:
        if value is None:
            facts.append(KeyFact(label=title, value="Time not provided", detail=detail))
            return
        local = _local(value, timezone)
        text = f"{local.isoformat()} ({timezone or 'unknown timezone'}) · {detail}"
        if local.utcoffset() is None:
            facts.append(KeyFact(label=title, value=text))
            return
        stamps.append(local)
        timeline.append(TimelineItem(start=local, end=local, title=title, detail=f"{notice} · {text}",
                                     calendar_id=calendar_id))

    labels = {s.id: public_origin(plan.origin_public) if s.kind is StopKind.home else s.label for s in plan.stops}
    stops = {s.id: s for s in plan.stops}
    for stop in plan.stops:
        point(labels[stop.id], stop.local_time, stop.timezone, f"Stop {stop.id}", f"stop:{stop.id}")
    for segment in plan.segments:
        label = f"{labels[segment.from_stop_id]} → {labels[segment.to_stop_id]} ({segment.mode.value})"
        state = ("not automated" if segment.automation.value != "automated" else "automation planned, not committed")
        detail = f"{segment.id} · {state} ({segment.automation.value}) · {_money(segment.cost)}"
        url = segment.manual_url or (str(segment.limitation.manual_url) if segment.limitation and segment.limitation.manual_url else None)
        if url:
            manual_source = RecapSource(label=f"Manual official link: {label}", url=url,
                                       found_by="JourneyPlan", used_for=state)
            manual_sources.append(manual_source)
            detail += f" · Manual official link: {url}"
        elif state == "not automated":
            detail += " · official link unknown"
        facts.append(KeyFact(label=label, value=detail))
        point(f"Departure: {label}", segment.departure,
              stops[segment.from_stop_id].timezone or segment.timezone, detail, f"departure:{segment.id}")
        point(f"Arrival: {label}", segment.arrival,
              stops[segment.to_stop_id].timezone or segment.timezone, detail, f"arrival:{segment.id}")
        if segment.limitation:
            checklist.append(segment.limitation.message)
    for limitation in plan.limitations:
        checklist.append(f"{limitation.code} : {limitation.message}")
        if limitation.manual_url:
            manual_sources.append(RecapSource(label=limitation.code, url=str(limitation.manual_url),
                                             found_by="JourneyPlan", used_for="Manual alternative"))
    sources = [RecapSource(label=p.label or p.kind.value, url=str(p.url) if p.url else None,
                           found_by=p.kind.value) for p in plan.sources]
    # A fixed serialization epoch is metadata, not a claimed journey time.
    generated = min(stamps).astimezone(UTC) if stamps else datetime(1970, 1, 1, tzinfo=UTC)
    recap = Recap(id=f"{plan.mission_id}-r{plan.revision}-{plan.mode.value}", generated_at=generated,
                  calendar_id=f"{plan.mission_id}-{plan.mode.value}", calendar_revision=plan.revision,
                  race_name=plan.race_name or "Race to confirm", race_city="", runner_name="",
                  runner_fictive=False, notice=notice, key_facts=facts,
                  timeline=sorted(timeline, key=lambda item: item.start), checklist=checklist,
                  sources=sources + manual_sources, calendar_timezone="UTC")
    return JourneyRecap(plan.mission_id, plan.revision, plan.mode.value, plan.schema_version, recap.model_dump_json())


def render_html(snapshot: JourneyRecap) -> str:
    """Reuse the recap HTML, excluding its mission-only EUR/payment summary."""
    html = legacy_html(snapshot.recap)
    html = re.sub(r'<div class="kpis">.*?<div class="fine">.*?</div>', '', html, count=1, flags=re.DOTALL)
    html = re.sub(r" · generated on .*?</div>", "</div>", html, count=1)
    return html.replace("Your race weekend is ready", "Your trip is prepared, not booked").replace(
        "The links above take you back to the page where the agent stopped.",
        "You must check the manual official links yourself.")


def render_pdf(snapshot: JourneyRecap, chrome: str | None = None) -> bytes:
    """Print exactly the snapshot HTML with the existing Chrome PDF renderer."""
    return html_to_pdf(render_html(snapshot), chrome)


def render_ics(snapshot: JourneyRecap) -> bytes:
    """Calendar instants in UTC; original IANA zones remain in descriptions."""
    text = legacy_ics(snapshot.recap).decode()
    text = re.sub(r"DTEND:[^\r\n]*\r\n", "", text)
    recap = snapshot.recap
    description = "\n".join([recap.notice or "", *[f"{f.label}: {f.value}" for f in recap.key_facts],
                              *recap.checklist, *[s.url for s in recap.sources if s.url]])
    metadata = [f"X-RUNAI-SCHEMA:{escape_text(snapshot.schema_version)}",
                f"X-RUNAI-MISSION-ID:{escape_text(snapshot.mission_id)}",
                f"X-RUNAI-REVISION:{snapshot.revision}", f"X-RUNAI-MODE:{snapshot.mode}",
                f"X-WR-CALDESC:{escape_text(description)}"]
    content, separator, tail = text.rpartition("END:VCALENDAR")
    return (content + "\r\n".join(fold(line) for line in metadata) + "\r\n" + separator + tail).encode()
