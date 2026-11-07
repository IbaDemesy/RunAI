import re
from urllib.parse import urlsplit

from runai.models import TraceEvent

_CAPTCHA_ERROR = (
    "Site protégé par un captcha : l'agent s'est arrêté. "
    "Finissez cette étape vous-même sur le site officiel."
)
_TIMEOUT_ERROR = (
    "Le site a mis trop de temps à répondre. Vous pouvez reprendre cette étape vous-même."
)
_SERVICE_ERROR = "Le service d'agents est indisponible pour le moment."
_GENERIC_ERROR = (
    "L'agent n'a pas pu terminer cette étape. Vous pouvez la faire vous-même "
    "depuis le site officiel."
)
_STOPPED_HEADLINE = "Prêt : à finaliser vous-même sur le site officiel"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _observation_headline(event: TraceEvent) -> str | None:
    payload = event.data.get("event")
    payload = payload if isinstance(payload, dict) else event.data
    agent_data = payload.get("data")
    agent_data = agent_data if isinstance(agent_data, dict) else {}
    metadata = agent_data.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    url = metadata.get("url") or event.data.get("url")
    if not isinstance(url, str):
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    if host.lower().startswith("www."):
        host = host[4:]
    title = metadata.get("title") or event.data.get("title")
    page = f"Sur {host}"
    if isinstance(title, str) and title:
        page += f" · {title[:80]}{'…' if len(title) > 80 else ''}"
    return _truncate(page, 120)


def friendly_error(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ("captcha", "anti-bot", "blocage")):
        return _CAPTCHA_ERROR
    if "timeout" in lowered or "timed out" in lowered:
        return _TIMEOUT_ERROR
    if (
        any(token in lowered for token in ("api key", "hai_api_key", "unauthorized", "forbidden"))
        or re.search(
            r"\b(?:http|status|code|erreur)\D{0,3}40[13]\b(?!\s*(?:€|euros?\b))",
            lowered,
        )
    ):
        return _SERVICE_ERROR
    if text and text[0].isupper() and not re.search(
        r"traceback|error|exception", text, re.IGNORECASE
    ):
        return text
    return _GENERIC_ERROR


def headline(event: TraceEvent) -> str | None:
    if event.type == "AgentEvent.observation_event":
        return _observation_headline(event)
    if event.type == "step_started":
        return "Ouverture du navigateur…"
    if event.type == "question" and event.message:
        return _truncate(f"Attend votre réponse : {event.message}", 120)
    if event.type in {"AgentErrorEvent", "AgentEvent.error_event"}:
        return _truncate(friendly_error(event.message or ""), 120)
    return None
