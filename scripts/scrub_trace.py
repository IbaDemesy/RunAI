"""Create publishable JSONL traces: python -m scripts.scrub_trace INPUT OUTPUT."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from runai.models import RunnerProfile
from runai.redaction import redact_secrets

_H_KEY = re.compile(r"\bhk-[A-Za-z0-9_-]+", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PRIVATE_KEYS = {"agent_view_url", "live_view_url"}
_RESOURCE = re.compile(r"/api/v1/trajectories/", re.IGNORECASE)
_PHONE_KEYS = {"phone", "phone_number", "telephone", "mobile"}


def scrub_event(obj: Any) -> Any:
    """Return a sanitized copy, preserving public share links."""
    obj = redact_secrets(obj)

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                walk(key): "+33000000000" if key.lower() in _PHONE_KEYS else walk(item)
                for key, item in value.items()
                if key.lower() not in _PRIVATE_KEYS
                and not _RESOURCE.search(key)
                and not (isinstance(item, str) and _RESOURCE.search(item))
            }
        if isinstance(value, list):
            return [walk(item) for item in value if not (isinstance(item, str) and _RESOURCE.search(item))]
        if isinstance(value, str):
            if _RESOURCE.search(value):
                return "[REDACTED]"
            value = _H_KEY.sub("[REDACTED]", value)
            value = value.replace(RunnerProfile().email, "runner@example.com")
            return _EMAIL.sub(
                lambda match: match.group() if match[1].lower() == "example.com" else "runner@example.com", value
            )
        return value

    return walk(obj)


def find_violations(obj: Any) -> list[str]:
    """Locate forbidden credentials, private links, and non-example emails."""
    violations = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in _PRIVATE_KEYS and item is not None:
                    violations.append(f"{path}: private field {key}")
                walk(key, path)
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            if _H_KEY.search(value):
                violations.append(f"{path}: H key token")
            if _RESOURCE.search(value):
                violations.append(f"{path}: private H resource URL")
            if any(match[1].lower() != "example.com" for match in _EMAIL.finditer(value)):
                violations.append(f"{path}: non-example email")

    walk(obj, "$")
    return violations


def _changes(before: Any, after: Any) -> int:
    if isinstance(before, dict) and isinstance(after, dict):
        return sum(1 if key not in after else _changes(value, after[key]) for key, value in before.items())
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return sum(_changes(a, b) for a, b in zip(before, after))
    return int(before != after)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    events = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    sanitized = [scrub_event(event) for event in events]
    fields = sum(_changes(event, clean) for event, clean in zip(events, sanitized))
    args.output.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in sanitized))
    print(f"Events kept: {len(sanitized)}; fields scrubbed: {fields}")


if __name__ == "__main__":
    main()
