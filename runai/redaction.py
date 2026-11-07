"""Mask configured provider credentials before publishing diagnostics."""

import os
import re
from typing import Any

_KEY_NAME = re.compile(r"(?:HAI|GLADIA|LINKUP)_API_KEY(?:_\d+)?\Z")


def redact_secrets(value: Any) -> Any:
    secrets = sorted(
        {secret for name, secret in os.environ.items() if _KEY_NAME.fullmatch(name) and len(secret) >= 8},
        key=len,
        reverse=True,
    )

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        if isinstance(item, dict):
            return {walk(key): walk(content) for key, content in item.items()}
        if isinstance(item, list):
            return [walk(content) for content in item]
        if isinstance(item, tuple):
            return tuple(walk(content) for content in item)
        return item

    return walk(value)
