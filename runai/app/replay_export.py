"""Portable, redacted mission recordings."""

import re
from typing import Any

from runai.app.mission import Mission
from runai.app.replay import ReplayTrace
from runai.redaction import redact_secrets

_PRIVATE_KEYS = {
    "first_name", "last_name", "full_name", "email", "phone", "phone_number",
    "birth_date", "date_of_birth", "address", "passport", "password",
}


def _redact_personal(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _PRIVATE_KEYS else _redact_personal(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_personal(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED]", value)
        return re.sub(
            r"(?<![\w/=?&#:.-])(?!\d{4}-\d{2}-\d{2})\+?\d[\d ().-]{7,}\d(?![\w/-])",
            "[REDACTED]", value,
        )
    return value


def export_replay(mission: Mission) -> ReplayTrace:
    trace = ReplayTrace.from_mission_snapshot(mission.snapshot(include_events=True))
    mode = mission.plan.mode if mission.plan else trace.recorded_mode
    trace.recorded_mode = mode
    trace.race = mission.race
    race_name = mission.race.name if mission.race else "Unknown race"
    trace.label = f"Replay of {race_name} recorded in {mode.value}"
    trace.transcript = next(
        (turn.text for turn in mission.framing_turns if turn.channel == "voice"), None
    )
    return ReplayTrace.model_validate(_redact_personal(redact_secrets(trace.model_dump(mode="json"))))
