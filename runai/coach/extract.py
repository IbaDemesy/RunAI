"""Runner interview questions and bilingual extraction into `CoachProfile`.

Gladia transcripts can be passed to an LLM with `llm_prompt()` and `parse_llm_json()`.
The rule-based fallback only fills explicitly stated information. Plausibility checks
clear suspect fields and request another answer to the corresponding question.
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from runai.coach.models import CoachProfile, Goal, RecentRace, RecentRun

QUESTIONS: list[str] = [
    "How many times a week do you run now, and roughly how many kilometres?",
    "What was your longest run in recent weeks: how far, and how long did it take?",
    "Do you have a recent race time for a 5K, 10K, half marathon or marathon? Which race, and when?",
    "How long have you been running, and how old are you?",
    "What appeals to you: your first 10K, a PR, trail running, or running abroad?",
]

# Question index for each profile field.
FIELD_QUESTION: dict[str, int] = {
    "sessions_per_week": 0,
    "weekly_km": 0,
    "longest_recent_run": 1,
    "recent_race": 2,
    "cooper_m": 2,
    "running_since_months": 3,
    "age": 3,
    "goals": 4,
}

CUSTOM_VOCABULARY: list[str] = [
    "semi", "marathon", "trail", "D+", "dénivelé", "Cooper", "chrono", "10 km", "VMA",
    "half marathon", "elevation gain", "PR", "pace", "10K", "VO2max",
]

_LLM_PROMPT = (
    "Extract a runner's profile from their transcribed answers in English or French. "
    "Reply ONLY with a valid JSON object matching this JSON schema. "
    "Unstated information must be null (or [] for goals); never guess or invent. "
    "Use seconds for recent_race.time_s and minutes for longest_recent_run.duration_min. "
    "Convert miles to kilometres (1 mile = 1.609344 km). "
    "'half marathon', 'half' or 'semi' = 21.0975 km; 'marathon' = 42.195 km. "
    "months_ago is the age of the race result in months. "
    "Map first 10K, PR/PB, trail, travel/abroad and finish goals to "
    "premier_10k, chrono, trail, voyage and finir respectively.\nSchema: "
)


def llm_prompt() -> str:
    """LLM instructions (including Gladia `audio_to_llm`) with the profile schema."""
    schema = CoachProfile.model_json_schema(mode="validation")
    return _LLM_PROMPT + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def parse_llm_json(text: str) -> CoachProfile:
    """Validate LLM output, accepting fenced JSON; raise `ValueError` if invalid."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("no JSON object in the LLM response")
    data = json.loads(match.group(0))
    data.pop("missing_fields", None)
    return CoachProfile.model_validate(data)


_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}  # fmt: skip
_NUM = r"(\d+(?:[.,]\d+)?)"
_DIST_WORDS = {"half marathon": 21.0975, "half": 21.0975, "semi-marathon": 21.0975, "semi": 21.0975, "marathon": 42.195}
_CHRONO_HINT = r"(?:chrono|course|couru|fait|termin\w*|boucl\w*|\bran\b|race|completed|finished|\bdid\b)"


_ET_COMPOUNDS = {(20, 1), (30, 1), (40, 1), (50, 1), (60, 1), (60, 11)}


def _normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(\d) (\d{3})\b", r"\1\2", t)
    tens = "vingt|trente|quarante|cinquante|soixante|twenty|thirty|forty|fifty|sixty"
    units = "un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|one|two|three|four|five|seven|eight|nine"
    t = re.sub(  # "vingt-deux", "twenty two": the only place where two words make one number
        rf"\b({tens})[- ]({units})\b",
        lambda m: str(_NUMBER_WORDS[m[1]] + _NUMBER_WORDS[m[2]]),
        t,
    )
    t = re.sub(r"\b(?:un|une)\s+(?=" + r"\d+(?:[.,]\d+)?\s*(?:km|k|kilom\w*|miles?)\b)", "", t)
    for word, value in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{word}\b", str(value), t)
    t = re.sub(
        r"\b(\d+) et (\d+)\b",
        lambda m: str(int(m[1]) + int(m[2])) if (int(m[1]), int(m[2])) in _ET_COMPOUNDS else m[0],
        t,
    )
    t = re.sub(r"\bentre (\d+) et (\d+)\b", lambda m: f"{(int(m[1]) + int(m[2])) / 2:g}", t)
    t = re.sub(r"\b(\d+) et demi(e)?\b", lambda m: f"{m[1]}.5", t)
    return re.sub(r"\b(?:kilomètres|kilometres|kilometers|bornes)\b", "km", t)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _duration_s(text: str, distance_km: float | None = None) -> float | None:
    m = re.search(r"\b(\d+):([0-5]\d)(?::([0-5]\d))?\b", text)
    if m:
        if m[3] is None:
            as_min_s = int(m[1]) * 60 + int(m[2])
            if distance_km:
                hours_pace = as_min_s / distance_km  # min/km if read as h:mm
                if hours_pace > 15:
                    return as_min_s
            elif int(m[1]) >= 10:
                return as_min_s
        return int(m[1]) * 3600 + int(m[2]) * 60 + (int(m[3]) if m[3] else 0)
    m = re.search(rf"{_NUM}\s*h(?:eures?)?\s*(?:(\d{{1,2}})(?:\s*(?:min\w*|'))?)?", text)
    if m:
        return _num(m[1]) * 3600 + (int(m[2]) * 60 if m[2] else 0)
    m = re.search(rf"{_NUM}\s*(?:min\w*|')\s*(?:(\d{{1,2}})\s*(?:s\w*|\"))?", text)
    if m:
        return _num(m[1]) * 60 + (int(m[2]) if m[2] else 0)
    return None


def _distance_km(text: str) -> float | None:
    if re.search(r"\d+\s+\d+\s*(?:km|k|miles?)\b", text):
        return None  # Ambiguous transcription: ask again rather than guess.
    m = re.search(rf"{_NUM}\s*(km|k|miles?)\b", text)
    if m:
        return _num(m[1]) * (1.609344 if m[2].startswith("mile") else 1)
    for word, km in _DIST_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return km
    return None


def extract_rule_based(transcript: str) -> CoachProfile:
    """Extract explicitly stated information using bilingual rules, without an LLM."""
    t = _normalize(transcript)
    data: dict[str, Any] = {}
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+|\n", t) if s.strip()]

    frequency = r"(?:fois|sorties?|séances?|seances?)\s*(?:par|/|a la|à la)\s*semaine|(?:times?|runs?|sessions?)\s*(?:a|per|/)\s*week"
    m = re.search(rf"{_NUM}\s*(?:{frequency})", t)
    if m:
        data["sessions_per_week"] = _num(m[1])
    m = re.search(rf"{_NUM}\s*(km|miles?)\s*(?:(?:par|/|a la|à la)\s*semaine|(?:a|per|/)\s*week)", t)
    if m is None:
        m = re.search(rf"(?:{frequency})[^.!?;\n]*?{_NUM}\s*(km|miles?)", t)
    if m:
        data["weekly_km"] = _num(m[1]) * (1.609344 if m[2].startswith("mile") else 1)

    for s in sentences:
        timed = re.split(r"\s(?:en|in)\s", s, maxsplit=1)
        after = timed[1] if len(timed) == 2 else ""
        if "plus longue" in s or "sortie longue" in s or "longest run" in s or "long run" in s:
            dist = _distance_km(s)
            if dist is not None:
                duration_s = _duration_s(after, dist)
                dplus = re.search(r"(\d+)\s*(?:m(?:ètres?|etres?|eters?)?\s*(?:de\s*|of\s*)?(?:d\+|dénivelé|denivele|elevation gain))", s)
                data["longest_recent_run"] = RecentRun(
                    distance_km=dist,
                    duration_min=duration_s / 60 if duration_s else None,
                    d_plus_m=int(dplus[1]) if dplus else None,
                )
            continue
        if re.search(_CHRONO_HINT, s) and after and not re.search(r"semaine|week", s):
            dist = _distance_km(s)
            dur = _duration_s(after, dist)
            if dist is not None and dur:
                months = 0.0
                ago = re.search(rf"(?:il y a|ça fait|ca fait)\s*{_NUM}\s*(mois|ans?|semaines?)", s)
                if ago:
                    factor = {"mois": 1, "an": 12, "ans": 12}.get(ago[2], 0.25)
                    months = _num(ago[1]) * factor
                elif ago := re.search(rf"{_NUM}\s*(months?|years?|weeks?)\s+ago", s):
                    factor = 12 if ago[2].startswith("year") else 0.25 if ago[2].startswith("week") else 1
                    months = _num(ago[1]) * factor
                elif "année dernière" in s or "l'an dernier" in s or "annee derniere" in s or "last year" in s:
                    months = 12
                try:
                    data["recent_race"] = RecentRace(distance_km=dist, time_s=int(dur), months_ago=months)
                except ValidationError:
                    pass

    m = re.search(rf"cooper.*?{_NUM}\s*(?:m\b|mètres|metres)", t) or re.search(
        rf"{_NUM}\s*(?:m\b|mètres|metres).*?cooper", t
    )
    if m and 800 <= _num(m[1]) <= 5000:
        data["cooper_m"] = int(_num(m[1]))
    m = re.search(rf"(?:j'ai|âgée? de|agee? de)\s*{_NUM}\s*ans\b", t) or re.search(
        rf"\b(?:i am|i'm|aged)\s*{_NUM}\b(?!\s*(?:weeks?|months?|days?|km|k\b|miles?|min|minutes?|hours?|h\b|times|kg|m\b|%|:)"
        rf"|\s+years?\s+(?:into|of|in)\b|\s*(?:semaines?|mois|jours?)\b)",
        t,
    )
    if m and 8 <= _num(m[1]) <= 100:
        data["age"] = int(_num(m[1]))
    m = re.search(rf"(?:depuis|ça fait|ca fait)\s*{_NUM}\s*(mois|ans?)\s*(?:que je cours|de course)?", t)
    if m and ("cour" in t[m.start() : m.end() + 25] or "depuis" in m[0]):
        data["running_since_months"] = int(_num(m[1]) * (1 if m[2] == "mois" else 12))
    m = re.search(rf"\brunning for\s*{_NUM}\s*(months?|years?)\b", t)
    if m:
        data["running_since_months"] = int(_num(m[1]) * (12 if m[2].startswith("year") else 1))

    def wanted(pattern: str) -> bool:
        """True when a match is not negated earlier in its own sentence ("I do not run trail")."""
        for match in re.finditer(pattern, t):
            start = max(t.rfind(mark, 0, match.start()) for mark in ".!?;\n") + 1
            before = t[max(start, match.start() - 40) : match.start()]
            if not re.search(r"\b(?:not|never|no|pas|jamais|sans|ni|don't|dont|doesn't|won't|aucun\w*)\b|n't\b", before):
                return True
        return False

    goals = []
    if wanted(r"premier 10|1er 10|premier dix|first 10\s*k"):
        goals.append(Goal.premier_10k)
    if wanted(r"chrono|record|battre|sous les|\b(?:pr|pb)\b") and "pas de chrono" not in t:
        goals.append(Goal.chrono)
    if wanted("trail"):
        goals.append(Goal.trail)
    if wanted(r"voyage|étranger|etranger|week-end|abroad|travel"):
        goals.append(Goal.voyage)
    if wanted(r"\bfinir\b|terminer|\bfinish\b"):
        goals.append(Goal.finir)
    data["goals"] = goals
    return CoachProfile(**data)


class PlausibilityIssue(BaseModel):
    field: str
    message: str


def plausibility_issues(p: CoachProfile) -> list[PlausibilityIssue]:
    """Find suspect transcription or LLM fields to clear and ask about again."""
    issues: list[PlausibilityIssue] = []
    run = p.longest_recent_run
    if run is not None and run.duration_min:
        pace = run.duration_min / run.distance_km
        if not 2.5 <= pace <= 12:
            issues.append(
                PlausibilityIssue(
                    field="longest_recent_run",
                    message=f"{run.distance_km:g} km in {run.duration_min:g} min ({pace:.1f} min/km)",
                )
            )
    if run is not None and p.weekly_km and run.distance_km > max(p.weekly_km, 10) * 1.2:
        issues.append(
            PlausibilityIssue(
                field="longest_recent_run",
                message=f"{run.distance_km:g} km > weekly volume {p.weekly_km:g} km",
            )
        )
    race = p.recent_race
    if race is not None:
        pace = race.time_s / 60 / race.distance_km
        if not 2.6 <= pace <= 12:
            issues.append(
                PlausibilityIssue(
                    field="recent_race",
                    message=f"{race.distance_km:g} km in {race.time_s} s ({pace:.1f} min/km)",
                )
            )
    if p.sessions_per_week and p.weekly_km and p.weekly_km / p.sessions_per_week > 40:
        issues.append(PlausibilityIssue(field="weekly_km", message="more than 40 km per run"))
    return issues


class ProfileExtraction(BaseModel):
    """Cleaned profile and follow-up questions for the runner."""

    profile: CoachProfile
    method: Literal["llm", "regles"]
    issues: list[PlausibilityIssue] = Field(default_factory=list)
    cleared_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    llm_error: str | None = None


def extract_profile(text: str, llm_json: str | None = None) -> ProfileExtraction:
    """Validate a transcript with optional LLM output, falling back to bilingual rules.

    Implausible fields are cleared and listed in `follow_up_questions`. Unstated
    information remains in `profile.missing_fields`; unknown answers are valid.
    """
    method: Literal["llm", "regles"] = "regles"
    llm_error = None
    profile: CoachProfile | None = None
    if llm_json is not None:
        try:
            profile = parse_llm_json(llm_json)
            method = "llm"
        except (ValueError, ValidationError) as exc:
            llm_error = str(exc).splitlines()[0][:200]
    if profile is None:
        profile = extract_rule_based(text)

    issues = plausibility_issues(profile)
    cleared = list(dict.fromkeys(issue.field for issue in issues))
    if cleared:
        profile = profile.model_copy(update=dict.fromkeys(cleared))
        profile = CoachProfile.model_validate(profile.model_dump(exclude={"missing_fields"}))

    indexes = list(dict.fromkeys(FIELD_QUESTION[name] for name in cleared))
    return ProfileExtraction(
        profile=profile,
        method=method,
        issues=issues,
        cleared_fields=cleared,
        follow_up_questions=[QUESTIONS[i] for i in indexes],
        llm_error=llm_error,
    )
