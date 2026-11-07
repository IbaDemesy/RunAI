"""Coach RunAI : « quel coureur es-tu ? » puis 3 à 5 courses ouvertes adaptées.

API (voir docs/COACH.md) :

    from runai.coach import QUESTIONS, extract_profile, assess, recommend_races, RacePreferences

    extraction = extract_profile(transcript)          # CoachProfile + champs à reposer
    assessment = assess(extraction.profile)           # niveau, fourchettes, verdict par distance
    result = recommend_races(assessment, RacePreferences(origin_city="Paris"), mode="replay")
    race = result.races[0].to_race()                  # runai.models.Race pour lancer une mission
"""

from runai.coach.cache import FIXTURES_DIR, DiscoveryCache
from runai.coach.demo import DEMO_PREFERENCES, DEMO_TRANSCRIPT
from runai.coach.extract import (
    CUSTOM_VOCABULARY,
    QUESTIONS,
    PlausibilityIssue,
    ProfileExtraction,
    extract_profile,
    extract_rule_based,
    llm_prompt,
    parse_llm_json,
    plausibility_issues,
)
from runai.coach.finder import OpenMeteoGeocoder, RaceFinder
from runai.coach.level import assess, estimate_level, trail_time_range
from runai.coach.models import (
    Assessment,
    CandidateRace,
    CoachProfile,
    DiscoveryResult,
    DistanceAdvice,
    Goal,
    Level,
    LevelEstimate,
    RacePreferences,
    RaceRecommendation,
    RecentRace,
    RecentRun,
    Recommendations,
    RegistrationStatus,
    SearchQuery,
    TimeRange,
)
from runai.coach.recommend import CacheMiss, build_query, rank_races, recommend_races

__all__ = [
    "CUSTOM_VOCABULARY",
    "DEMO_PREFERENCES",
    "DEMO_TRANSCRIPT",
    "FIXTURES_DIR",
    "QUESTIONS",
    "Assessment",
    "CacheMiss",
    "CandidateRace",
    "CoachProfile",
    "DiscoveryCache",
    "DiscoveryResult",
    "DistanceAdvice",
    "Goal",
    "Level",
    "LevelEstimate",
    "OpenMeteoGeocoder",
    "PlausibilityIssue",
    "ProfileExtraction",
    "RaceFinder",
    "RacePreferences",
    "RaceRecommendation",
    "RecentRace",
    "RecentRun",
    "Recommendations",
    "RegistrationStatus",
    "SearchQuery",
    "TimeRange",
    "assess",
    "build_query",
    "estimate_level",
    "extract_profile",
    "extract_rule_based",
    "llm_prompt",
    "parse_llm_json",
    "plausibility_issues",
    "rank_races",
    "recommend_races",
    "trail_time_range",
]
