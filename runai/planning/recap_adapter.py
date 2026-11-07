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


def _money(value: Money | None) -> str:
    return f"{value.amount} {value.currency}" if value else "non chiffré (not priced)"


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
    prepared = "Préparé ≠ réservé : aucun élément réservé, payé ou confirmé."
    mode = {"demo": "DEMO — données de démonstration, pas des données live.",
            "replay": "REPLAY — rejeu enregistré, pas des données live.",
            "live": "Mode live — préparation uniquement."}[plan.mode.value]
    notice = f"{identity} · {mode} {prepared}"
    facts = [KeyFact(label="Snapshot", value=identity),
             KeyFact(label="Origine publique", value=public_origin(plan.origin_public))]
    if plan.date_range:
        facts.append(KeyFact(label="Dates", value=" → ".join(d.isoformat() for d in plan.date_range)))
    budget = plan.budget
    facts.extend([
        KeyFact(label="Total connu" + (" partiel" if not budget.complete else ""),
                value=f"{budget.known_total} {budget.currency}"),
        KeyFact(label="Plafond", value=str(budget.cap) + " " + budget.currency if budget.cap is not None else "inconnu"),
        KeyFact(label="Dépassement du plafond", value="unknown" if budget.over_cap is None else str(budget.over_cap).lower()),
    ])
    for line in budget.lines:
        facts.append(KeyFact(label=line.label, value=_money(line.money), detail=line.note))
    checklist = list(plan.warnings)
    manual_sources = []
    timeline = []
    stamps = []

    def point(title: str, value: datetime | None, timezone: str | None, detail: str) -> None:
        if value is None:
            facts.append(KeyFact(label=title, value="Horaire inconnu", detail=detail))
            return
        local = _local(value, timezone)
        text = f"{local.isoformat()} ({timezone or 'fuseau inconnu'}) · {detail}"
        if local.utcoffset() is None:
            facts.append(KeyFact(label=title, value=text))
            return
        stamps.append(local)
        timeline.append(TimelineItem(start=local, end=local, title=title, detail=f"{notice} · {text}"))

    labels = {s.id: public_origin(plan.origin_public) if s.kind is StopKind.home else s.label for s in plan.stops}
    stops = {s.id: s for s in plan.stops}
    for stop in plan.stops:
        point(labels[stop.id], stop.local_time, stop.timezone, f"Étape {stop.id}")
    for segment in plan.segments:
        label = f"{labels[segment.from_stop_id]} → {labels[segment.to_stop_id]} ({segment.mode.value})"
        state = ("non automatisé" if segment.automation.value != "automated" else "automatisation prévue, non engagée")
        detail = f"{segment.id} · {state} ({segment.automation.value}) · {_money(segment.cost)}"
        url = segment.manual_url or (str(segment.limitation.manual_url) if segment.limitation and segment.limitation.manual_url else None)
        if url:
            manual_source = RecapSource(label=f"Lien officiel manuel : {label}", url=url,
                                       found_by="JourneyPlan", used_for=state)
            manual_sources.append(manual_source)
            detail += f" · Lien officiel manuel : {url}"
        elif state == "non automatisé":
            detail += " · lien officiel inconnu"
        facts.append(KeyFact(label=label, value=detail))
        point(f"Départ : {label}", segment.departure,
              stops[segment.from_stop_id].timezone or segment.timezone, detail)
        point(f"Arrivée : {label}", segment.arrival,
              stops[segment.to_stop_id].timezone or segment.timezone, detail)
        if segment.limitation:
            checklist.append(segment.limitation.message)
    for limitation in plan.limitations:
        checklist.append(f"{limitation.code} : {limitation.message}")
        if limitation.manual_url:
            manual_sources.append(RecapSource(label=limitation.code, url=str(limitation.manual_url),
                                             found_by="JourneyPlan", used_for="Alternative manuelle"))
    sources = [RecapSource(label=p.label or p.kind.value, url=str(p.url) if p.url else None,
                           found_by=p.kind.value) for p in plan.sources]
    # A fixed serialization epoch is metadata, not a claimed journey time.
    generated = min(stamps).astimezone(UTC) if stamps else datetime(1970, 1, 1, tzinfo=UTC)
    recap = Recap(id=f"{plan.mission_id}-r{plan.revision}-{plan.mode.value}", generated_at=generated,
                  race_name=f"Séjour · {plan.mission_id}", race_city="", runner_name="toi",
                  runner_fictive=False, notice=notice, key_facts=facts,
                  timeline=sorted(timeline, key=lambda item: item.start), checklist=checklist,
                  sources=sources + manual_sources, calendar_timezone="UTC")
    return JourneyRecap(plan.mission_id, plan.revision, plan.mode.value, plan.schema_version, recap.model_dump_json())


def render_html(snapshot: JourneyRecap) -> str:
    """Reuse the recap HTML, excluding its mission-only EUR/payment summary."""
    html = legacy_html(snapshot.recap)
    html = re.sub(r'<div class="kpis">.*?<div class="fine">.*?</div>', '', html, count=1, flags=re.DOTALL)
    html = re.sub(r" · généré le .*?</div>", "</div>", html, count=1)
    return html.replace("Ton week-end de course est prêt", "Ton séjour est préparé, pas réservé").replace(
        "Les liens ci-dessus te ramènent à la page où l'agent s'est arrêté.",
        "Les liens officiels manuels sont à vérifier par toi.")


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
    return text.replace("END:VCALENDAR", "\r\n".join(fold(line) for line in metadata) + "\r\nEND:VCALENDAR").encode()
