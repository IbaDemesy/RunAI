"""Deterministic mission accounting from trace timestamps and final results."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from runai.models import StepResult, TraceEvent
from runai.redaction import redact_secrets


class StepMetrics(BaseModel):
    status: str = "pending"
    stop_point: str | None = None
    duration_s: float = 0
    h_steps: int | None = None
    max_steps: int | None = None
    total_cost_usd: float | None = None
    events: int = 0
    unique_hosts: list[str] = Field(default_factory=list)
    questions: int = 0
    human_wait_s: float = 0
    h_session_id: str | None = None
    h_key: str | None = None
    provider: Literal["h"] = "h"


class Totals(BaseModel):
    h_cost_usd: float = 0
    h_steps: int = 0
    agents: int = 0


class MissionMetrics(BaseModel):
    mission_id: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    wall_s: float = 0
    time_to_first_agent_event_s: float | None = None
    human_wait_s: float = 0
    steps: dict[str, StepMetrics] = Field(default_factory=dict)
    totals: Totals = Field(default_factory=Totals)


def compute(
    mission_id: str,
    events: Sequence[TraceEvent],
    steps: Mapping[str, StepResult] | None = None,
    status: str | None = None,
) -> MissionMetrics:
    """Use the latest event as the clock; unknown usage remains None, not zero."""
    ordered = sorted(events, key=lambda event: event.at)
    results = {str(getattr(key, "value", key)): value for key, value in (steps or {}).items()}
    grouped: dict[str, list[TraceEvent]] = {key: [] for key in results}
    for event in ordered:
        kind = event.data.get("step")
        if not kind and event.source.startswith("agent:"):
            kind = event.source.split(":", 1)[1]
        if isinstance(kind, str) and kind != "search":
            grouped.setdefault(kind, []).append(event)
    grouped.pop("search", None)
    latest = ordered[-1].at if ordered else None
    computed = {}
    for kind, trace in grouped.items():
        result = results.get(kind)
        metric = StepMetrics()
        if result:
            metric.status = result.status.value
            metric.stop_point = result.stop_point.value if result.stop_point else None
            metric.h_session_id = result.h_session_id
            metric.h_steps = result.data.get("steps")
            metric.total_cost_usd = result.data.get("total_cost")
            metric.max_steps = result.data.get("max_steps")
            metric.h_key = result.data.get("h_key")
        starts = [event.at for event in trace if event.type == "step_started"]
        ends = [event.at for event in trace if event.type in {"step_done", "step_failed"}]
        start = starts[0] if starts else (trace[0].at if trace else None)
        end = ends[-1] if ends else latest
        if start and end:
            metric.duration_s = max(0, (end - start).total_seconds())
        hosts = set()
        questions: dict[str, datetime] = {}
        for event in trace:
            data = event.data
            if not result:
                if event.type == "step_started":
                    metric.status = "running"
                elif event.type == "step_failed":
                    metric.status = "failed"
                elif event.type == "step_done":
                    metric.status = data.get("status", "completed")
                elif event.type == "question":
                    metric.status = "waiting_for_user"
                elif event.type == "answer":
                    metric.status = "running"
                metric.stop_point = data.get("stop_point", metric.stop_point)
            metric.h_session_id = data.get("h_session_id", metric.h_session_id)
            if event.type == "session_created":
                metric.h_key = data.get("h_key", metric.h_key)
                metric.max_steps = data.get("max_steps", metric.max_steps)
            payload = data.get("event", {}).get("data", {})
            if event.type == "MetricsUpdateEvent":
                usage = payload.get("metrics", data.get("metrics", {}))
                if usage.get("steps") is not None:
                    metric.h_steps = usage["steps"]
                if usage.get("total_cost") is not None:
                    metric.total_cost_usd = usage["total_cost"]
            if event.type == "AgentEvent.observation_event":
                url = payload.get("metadata", {}).get("url")
                if isinstance(url, str):
                    try:
                        parsed = urlsplit(url)
                        if parsed.scheme in {"http", "https"} and parsed.hostname:
                            hosts.add(parsed.hostname)
                    except ValueError:
                        pass
            qid = data.get("question_id")
            if event.type == "question":
                metric.questions += 1
                if qid:
                    questions.setdefault(qid, event.at)
            elif event.type == "answer" and qid in questions:
                metric.human_wait_s += (event.at - questions.pop(qid)).total_seconds()
        metric.events = len(trace)
        metric.unique_hosts = sorted(hosts)
        computed[kind] = metric
    resolved_status = getattr(status, "value", status)
    if resolved_status is None:
        if any(event.type == "mission_cancelled" for event in ordered):
            resolved_status = "cancelled"
        elif any(step.status == "failed" for step in computed.values()):
            resolved_status = "failed"
        elif any(event.type == "mission_done" for event in ordered) or (
            computed and all(step.status in {"completed", "stopped_before_commitment"} for step in computed.values())
        ):
            resolved_status = "awaiting_human" if any(
                step.status == "stopped_before_commitment" for step in computed.values()
            ) else "completed"
        else:
            resolved_status = "running" if ordered else "pending"
    started = ordered[0].at if ordered else None
    first_agent = next((event.at for event in ordered if event.source == "h" or event.source.startswith("agent:")), None)
    report = MissionMetrics(
        mission_id=mission_id, status=resolved_status, started_at=started,
        ended_at=latest if resolved_status in {"completed", "failed", "cancelled", "awaiting_human"} else None,
        wall_s=(latest - started).total_seconds() if started and latest else 0,
        time_to_first_agent_event_s=(first_agent - started).total_seconds() if first_agent and started else None,
        human_wait_s=sum(step.human_wait_s for step in computed.values()), steps=computed,
        totals=Totals(h_cost_usd=sum(step.total_cost_usd or 0 for step in computed.values()),
                      h_steps=sum(step.h_steps or 0 for step in computed.values()), agents=len(computed)),
    )
    return MissionMetrics.model_validate(redact_secrets(report.model_dump()))
