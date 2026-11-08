"""Parse and format race durations ('2h10', '3h15', '2:10:30', '130 min')."""

import re
from datetime import timedelta

_HMS = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_H_M = re.compile(r"^(\d{1,2})\s*h\s*(?:(\d{1,2})\s*(?:'|’|\x22|”|min|m)?)?$")
_MIN = re.compile(r"^(\d{1,3})\s*(?:min|mn|')$")
_RANGE = re.compile(r"\s*(?:-|–|à|to|a)\s*")


def parse_duration(text: str) -> timedelta:
    """`2h10`, `2 h 10 min`, `3h15'`, `6h30”`, `2:10` (h:mm), `2:10:30`, `130 min`."""
    value = text.strip().lower().replace(",", ".")
    if match := _HMS.match(value):
        hours, minutes, seconds = (int(part or 0) for part in match.groups())
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if match := _H_M.match(value):
        return timedelta(hours=int(match.group(1)), minutes=int(match.group(2) or 0))
    if match := _MIN.match(value):
        return timedelta(minutes=int(match.group(1)))
    raise ValueError(f"Unrecognized duration: {text!r}")


def parse_duration_range(text: str) -> tuple[timedelta, timedelta]:
    """`2h10-2h15` -> (2h10, 2h15); a single value -> (v, v). Sort bounds in ascending order."""
    parts = [part for part in _RANGE.split(text.strip()) if part]
    if len(parts) == 2 and re.fullmatch(r"\d{1,2}", parts[1]) and "h" in parts[0]:
        parts[1] = parts[0].split("h")[0] + "h" + parts[1]
    if len(parts) not in (1, 2):
        raise ValueError(f"Unrecognized goal: {text!r}")
    values = sorted(parse_duration(part) for part in parts)
    return values[0], values[-1]


def format_duration(value: timedelta) -> str:
    total = round(value.total_seconds() / 60)
    hours, minutes = divmod(total, 60)
    return f"{hours}h{minutes:02d}"
