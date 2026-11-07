"""Mask configured credentials before publishing diagnostics."""

import base64
import os
import re
from typing import Any

_KEY_NAME = re.compile(r"[A-Z0-9_]*_API_KEY(?:_\d+)?\Z")
_BASIC_AUTH = "RUNAI_BASIC_AUTH"
_AUTH_HEADER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_AUTH_KEY = re.compile(r"(?:proxy-)?authorization\Z", re.IGNORECASE)
_MASK = "[REDACTED]"
_MIN_LEN = 8


def _configured_secrets() -> list[str]:
    found = {secret for name, secret in os.environ.items() if _KEY_NAME.fullmatch(name)}
    if credentials := os.environ.get(_BASIC_AUTH):
        found.add(credentials)
        found.add(base64.b64encode(credentials.encode()).decode())
        found.add(credentials.partition(":")[2])
    return sorted((s for s in found if len(s) >= _MIN_LEN), key=len, reverse=True)


def redact_secrets(value: Any) -> Any:
    secrets = _configured_secrets()

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, _MASK)
            return _AUTH_HEADER.sub(lambda m: f"{m.group(1)} {_MASK}", item)
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
