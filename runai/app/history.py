"""Per-user request history: compact, redacted summaries of missions held by the service.

Works from `MissionService.missions` only, so missions restored from disk at startup are
listed the same way as missions created in this process.
"""

from collections.abc import Iterable
from datetime import datetime

from runai.app.mission import TERMINAL_STATUSES, Mission
from runai.contracts.mission import (
    MissionSummary,
    MissionSummaryRace,
    MissionSummaryStep,
)
from runai.models import StepStatus, StopPoint
from runai.redaction import redact_secrets

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
FINISH_EVENTS = ("mission_done", "mission_cancelled")


def _automated_steps(mission: Mission):
    automated = [
        step for step in mission.steps.values()
        if step.data.get("automation", "automated") == "automated"
    ]
    return automated or list(mission.steps.values())


def _finished_at(mission: Mission) -> datetime | None:
    if mission.status not in TERMINAL_STATUSES:
        return None
    if mission.finished_at is not None:
        return mission.finished_at
    for event in reversed(mission.events):
        if event.type in FINISH_EVENTS:
            return event.at
    return mission.events[-1].at if mission.events else None


def build_headline(mission: Mission) -> str:
    steps = _automated_steps(mission)
    total = len(steps)
    stopped = [step for step in steps if step.status is StepStatus.stopped_before_commitment]
    prepared = len(stopped)
    target = "payment" if all(s.stop_point is StopPoint.payment for s in stopped) else "your final confirmation"
    noun = "step" if total == 1 else "steps"
    status = mission.status.value
    if status in {"searching", "running"}:
        return f"In progress: {prepared} of {total} {noun} prepared so far"
    if status == "cancelled":
        return f"Cancelled after preparing {prepared} of {total} {noun}"
    if status == "failed" and prepared == 0:
        return "Failed before reaching any payment page"
    if status == "failed":
        return f"Partly failed: prepared up to {target} on {prepared} of {total} {noun}"
    return f"Prepared up to {target} on {prepared} of {total} {noun}"


def summarize(mission: Mission) -> MissionSummary:
    plan = mission.plan
    brief = plan.brief if plan else None
    framing = mission.framing_summary
    race = mission.race or (plan.race if plan else None)
    prices = [step.price_eur for step in mission.steps.values() if step.price_eur is not None]
    date_range = framing.date_range if framing else None
    if date_range is None and brief and brief.arrival and brief.departure:
        date_range = (brief.arrival, brief.departure)
    budget = brief.budget_total_eur if brief else None
    if budget is None and framing:
        budget = framing.budget_eur
    summary = MissionSummary(
        mission_id=mission.id,
        framing_id=plan.framing_id if plan else None,
        user_id=mission.user_id,
        mode=plan.mode if plan else None,
        status=mission.status.value,
        created_at=mission.created_at,
        finished_at=_finished_at(mission),
        race=MissionSummaryRace(
            name=race.name, city=race.city, country=race.country,
            race_date=race.race_date, distance_km=race.distance_km,
        ) if race else None,
        origin=(brief.origin if brief else None) or (framing.origin_public if framing else None),
        date_range=date_range,
        budget_eur=budget,
        total_price_eur=round(sum(prices), 2) if prices else None,
        steps=[
            MissionSummaryStep(
                kind=step.kind, status=step.status, automation=step.data.get("automation"),
                stop_point=step.stop_point,
                price_eur=step.price_eur, url=str(step.url) if step.url else None,
            )
            for step in mission.steps.values()
        ],
        headline=build_headline(mission),
        replay_available=mission.status in TERMINAL_STATUSES and race is not None,
    )
    return MissionSummary.model_validate(redact_secrets(summary.model_dump(mode="json")))


def list_summaries(
    missions: Iterable[Mission],
    *,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[MissionSummary]:
    """Newest first; `user_id=None` lists every mission (internal use, the API requires a user_id)."""
    selected = [
        (mission.created_at, index, mission)
        for index, mission in enumerate(missions)
        if (user_id is None or mission.user_id == user_id)
        and (status is None or mission.status.value == status)
    ]
    selected.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [summarize(mission) for _, _, mission in selected[: max(0, limit)]]
