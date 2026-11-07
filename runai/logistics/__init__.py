"""Logistique du week-end : règlement sourcé, « feu vert règlement » et timeline exportable en .ics.

    rules = extract_rules(race)                      # fixture Milan, cache, sinon Linkup
    verdict = eligibility(rules, profile, situation, RunnerGoal.parse("3h45-3h55", 42.195))
    timeline = build_timeline(race, rules, arrival=train, hotel=hotel, departure=train_back)
    ics = to_ics(timeline)
"""

from runai.logistics.durations import (
    format_duration,
    parse_duration,
    parse_duration_range,
)
from runai.logistics.eligibility import choose_entry_path, eligibility, riegel
from runai.logistics.ics import to_ics
from runai.logistics.models import (
    Alert,
    AlertLevel,
    Eligibility,
    EntryPath,
    FieldSource,
    HotelStay,
    HumanTodo,
    LicenseKind,
    Light,
    PickupWindow,
    RaceRules,
    Reason,
    RecentResult,
    Requirement,
    RequirementKind,
    RunnerGoal,
    RunnerSituation,
    TimeGate,
    Timeline,
    TimelineEvent,
    TransportLeg,
)
from runai.logistics.rules import (
    RULES_SCHEMA,
    extract_rules,
    find_fixture,
    parse_rules_response,
)
from runai.logistics.timeline import build_timeline

__all__ = [
    "RULES_SCHEMA",
    "Alert",
    "AlertLevel",
    "Eligibility",
    "EntryPath",
    "FieldSource",
    "HotelStay",
    "HumanTodo",
    "LicenseKind",
    "Light",
    "PickupWindow",
    "RaceRules",
    "Reason",
    "RecentResult",
    "Requirement",
    "RequirementKind",
    "RunnerGoal",
    "RunnerSituation",
    "TimeGate",
    "Timeline",
    "TimelineEvent",
    "TransportLeg",
    "build_timeline",
    "choose_entry_path",
    "eligibility",
    "extract_rules",
    "find_fixture",
    "format_duration",
    "parse_duration",
    "parse_duration_range",
    "parse_rules_response",
    "riegel",
    "to_ics",
]
