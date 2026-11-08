"""Mask configured credentials before publishing diagnostics."""

import base64
import os
import re
from typing import Any

_KEY_NAME = re.compile(r"[A-Z0-9_]*_API_KEY(?:_\d+)?\Z")
_BASIC_AUTH = "RUNAI_BASIC_AUTH"
_BEARER = re.compile(
    r"\b(Bearer)\s+(?:(?=[A-Za-z]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,}|[A-Za-z]{16,})",
    re.IGNORECASE,
)
_BASIC = re.compile(r"\b(Basic)\s+([A-Za-z0-9+/]{4,}={0,2})(?![A-Za-z0-9+/=])", re.IGNORECASE)
_AUTH_KEY = re.compile(r"(?:proxy-)?authorization\Z", re.IGNORECASE)
_MASK = "[REDACTED]"
_MIN_LEN = 8
_H_KEY = re.compile(r"\bhk-[A-Za-z0-9_-]{16,}")
_URL_AUTH = re.compile(r"(https?://)[^\s/@]+:[^\s/@]*@", re.IGNORECASE)
_QUERY_SECRET = re.compile(r"([?&](?:token|access_token|api_key|key|secret)=)[^&#\s]*", re.IGNORECASE)


def _configured_secrets() -> list[str]:
    found = {secret for name, secret in os.environ.items() if _KEY_NAME.fullmatch(name)}
    if credentials := os.environ.get(_BASIC_AUTH):
        basic = {credentials, base64.b64encode(credentials.encode()).decode()}
        for pair in credentials.split(","):
            pair = pair.strip()
            basic.update((pair, base64.b64encode(pair.encode()).decode(), pair.partition(":")[2]))
    else:
        basic = set()
    return sorted({s for s in found if len(s) >= _MIN_LEN} | {s for s in basic if s}, key=len, reverse=True)


def _is_basic_credential(token: str) -> bool:
    try:
        return b":" in base64.b64decode(token, validate=True)
    except ValueError:
        return False


def redact_secrets(value: Any) -> Any:
    secrets = _configured_secrets()

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            item = _URL_AUTH.sub(lambda m: f"{m.group(1)}{_MASK}@", item)
            item = _QUERY_SECRET.sub(lambda m: f"{m.group(1)}{_MASK}", item)
            item = _H_KEY.sub(_MASK, item)
            for secret in secrets:
                item = item.replace(secret, _MASK)
            item = _BEARER.sub(lambda m: f"{m.group(1)} {_MASK}", item)
            return _BASIC.sub(lambda m: f"{m.group(1)} {_MASK}" if _is_basic_credential(m.group(2)) else m.group(0), item)
        if isinstance(item, dict):
            return {
                walk(key): _MASK if isinstance(key, str) and _AUTH_KEY.match(key) and content else walk(content)
                for key, content in item.items()
            }
        if isinstance(item, list):
            return [walk(content) for content in item]
        if isinstance(item, tuple):
            return tuple(walk(content) for content in item)
        return item

    return walk(value)
