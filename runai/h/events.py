import json
import unicodedata
from typing import Any

from runai.models import TraceEvent

MAX_TEXT = 500
_DROPPED_KEYS = {"image", "images", "page_html", "cookies", "headers", "authorization", "set-cookie", "password"}


def safe_text(value: str | None) -> str | None:
    """Bound untrusted agent text and remove invisible control/format characters."""
    if value is None:
        return None
    return "".join(
        " " if char.isspace() else char
        for char in value
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )[:2000]


def as_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return dict(vars(event))


def compact(value: Any, max_text: int = MAX_TEXT) -> Any:
    """Allège un événement H pour la trace : sans captures d'écran ni pages entières."""
    if isinstance(value, dict):
        return {
            k: v[:300] if k.lower() == "reasoning_content" and isinstance(v, str) else compact(v, max_text)
            for k, v in value.items()
            if k.lower() not in _DROPPED_KEYS
        }
    if isinstance(value, list):
        return [compact(v, max_text) for v in value]
    if isinstance(value, str):
        value = safe_text(value)
        if len(value) > max_text:
            return value[:max_text] + "…"
    return value


def answer_text(answer: Any) -> str | None:
    if answer is None:
        return None
    if isinstance(answer, str):
        return safe_text(answer)
    return safe_text(json.dumps(answer, ensure_ascii=False, default=str))


def event_label(event: dict[str, Any]) -> str:
    event_type = event.get("type") or "unknown"
    data = event.get("data") or {}
    if event_type == "AgentEvent" and isinstance(data, dict) and data.get("kind"):
        return f"{event_type}.{data['kind']}"
    return event_type


def event_summary(event: dict[str, Any]) -> str | None:
    data = event.get("data") or {}
    if not isinstance(data, dict):
        return None
    event_type = event.get("type")
    if event_type == "MetricsUpdateEvent":
        metrics = data.get("metrics")
        if not isinstance(metrics, dict):
            return None
        return f"step {metrics.get('steps') or 0} · ${metrics.get('total_cost') or 0:.2f}"
    if event_type == "LiveViewUrlEvent":
        return "vue live disponible"
    if event_type == "AgentRunStatusChangeEvent":
        return safe_text(data.get("status"))
    if event_type == "AgentErrorEvent":
        return safe_text(data.get("error"))
    if event_type == "AgentCompletionEvent":
        return safe_text(data.get("reason"))
    if event_type != "AgentEvent":
        return None
    kind = data.get("kind")
    if kind == "policy_event":
        text = data.get("content") or data.get("reasoning_content")
    elif kind == "observation_event":
        metadata = data.get("metadata") or {}
        text = " — ".join(part for part in (metadata.get("title"), metadata.get("url")) if part) or data.get("text")
    elif kind == "answer_event":
        text = answer_text(data.get("answer"))
    elif kind == "error_event":
        text = data.get("error")
    elif kind == "flow_event":
        text = data.get("flow")
    elif kind == "message_event":
        text = " ".join(str(part) for part in data.get("content") or [])
    else:
        text = None
    text = safe_text(text)
    if text is not None and len(text) > 200:
        return text[:200] + "…"
    return text


def to_trace_event(event: dict[str, Any], session_id: str, step: str) -> TraceEvent:
    if event.get("source") == "h" and event.get("type") == "metrics":
        # Already a RunAI metrics line emitted by HRun: keep its message and top-level fields.
        return TraceEvent.model_validate(event)
    return TraceEvent(
        source="h",
        type=event_label(event),
        message=event_summary(event),
        data={"h_session_id": session_id, "step": step, "event": compact(event)},
    )
