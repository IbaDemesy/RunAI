"""Portable, redacted mission recordings."""

import re
from typing import Any

from runai.app.mission import Mission
from runai.app.replay import ReplayTrace
from runai.redaction import redact_secrets

_PRIVATE_KEYS = {
    "first_name", "last_name", "full_name", "email", "phone", "phone_number",
    "birth_date", "date_of_birth", "address", "passport", "password",
    "emergency_contact_name", "emergency_contact_phone", "license_number", "pps_number",
    "birthdate", "birthday", "dob", "licence_number",
}
_PRIVATE_URL_KEYS = {"agent_view_url", "live_view_url"}
_TRAJECTORY_URL = re.compile(r"(?:https?://\S*?)?/api/v1/trajectories/[^\s\"'<>]*", re.IGNORECASE)
_URL = re.compile(r"(https?://[^\s\"'<>]+)")
_PHONE = re.compile(r"(?<![\w-])(?!\d{4}-\d{2}-\d{2})\+?\d[\d ().-]{7,}\d(?![\w-])")


def _redact_personal(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _PRIVATE_KEYS else _redact_personal(item)
            for key, item in value.items()
            if key.lower() not in _PRIVATE_URL_KEYS
        }
    if isinstance(value, list):
        return [_redact_personal(item) for item in value]
    if isinstance(value, str):
        value = _TRAJECTORY_URL.sub("[REDACTED]", value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED]", value)
        parts = _URL.split(value)
        return "".join(
            part if index % 2 else _PHONE.sub("[REDACTED]", part)
            for index, part in enumerate(parts)
        )
    return value


def _literal_values(profile: Any) -> list[str]:
    """Free-text occurrences of a real profile's identifying values (names, e-mail, phone, ids)."""
    if profile is None or getattr(profile, "fictional", True):
        return []
    fields = ("first_name", "last_name", "email", "phone", "emergency_contact_name", "emergency_contact_phone",
              "license_number", "pps_number", "club")
    values = {str(getattr(profile, name, None) or "").strip() for name in fields}
    birth = getattr(profile, "birth_date", None)
    if birth:
        values.add(birth.isoformat())
    return sorted((v for v in values if len(v) >= 3), key=len, reverse=True)


def _redact_literals(value: Any, literals: list[str]) -> Any:
    if isinstance(value, dict):
        return {key: _redact_literals(item, literals) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_literals(item, literals) for item in value]
    if isinstance(value, str):
        for literal in literals:
            value = re.sub(re.escape(literal), "[REDACTED]", value, flags=re.IGNORECASE)
    return value


def export_replay(mission: Mission, profile: Any = None) -> ReplayTrace:
    trace = ReplayTrace.from_mission_snapshot(mission.snapshot(include_events=True))
    mode = mission.plan.mode if mission.plan else trace.recorded_mode
    trace.recorded_mode = mode
    trace.race = mission.race
    race_name = mission.race.name if mission.race else "Unknown race"
    trace.label = f"Replay of {race_name} recorded in {mode.value}"
    trace.transcript = next(
        (turn.text for turn in mission.framing_turns if turn.channel == "voice"), None
    )
    data = _redact_personal(redact_secrets(trace.model_dump(mode="json")))
    return ReplayTrace.model_validate(_redact_literals(data, _literal_values(profile)))
