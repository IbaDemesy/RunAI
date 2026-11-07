"""Questions « Quel coureur es-tu ? » et extraction des réponses en `CoachProfile`.

Chaîne visée : Gladia (transcription, éventuellement `audio_to_llm`) -> LLM avec le schéma JSON
de `CoachProfile` (`llm_prompt()`) -> `parse_llm_json()`. Le parseur à règles sert de secours
sans LLM : il ne remplit que ce qui est dit. Dans les deux cas, `plausibility_issues()` repère les
erreurs de transcription (ex. mesuré le 07/11 : « 14 km en 1h20 » devenu « 100 km en 80 min ») ;
le champ fautif est remis à `None` et la question correspondante est reposée.
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from runai.coach.models import CoachProfile, Goal, RecentRace, RecentRun

QUESTIONS: list[str] = [
    "Combien de fois cours-tu par semaine en ce moment, et à peu près combien de kilomètres ?",
    "Quelle a été ta plus longue sortie ces dernières semaines : distance, et en combien de temps ?",
    "As-tu un chrono récent sur une course, 5 km, 10 km, semi ou marathon ? Si oui, lequel et quand ?",
    "Depuis combien de temps cours-tu, et quel âge as-tu ?",
    "Qu'est-ce qui te fait envie : un premier 10 km, battre un chrono, du trail, ou courir en voyage ?",
]

# Indice de la question (dans QUESTIONS) qui renseigne chaque champ.
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

CUSTOM_VOCABULARY: list[str] = ["semi", "marathon", "trail", "D+", "dénivelé", "Cooper", "chrono", "10 km", "VMA"]

_LLM_PROMPT = (
    "Tu extrais le profil d'un coureur à partir de la transcription de ses réponses. "
    "Réponds UNIQUEMENT par un objet JSON valide conforme à ce schéma JSON. "
    "Règles : une information non dite vaut null (ou [] pour goals), ne jamais deviner ni inventer ; "
    "temps en secondes pour recent_race.time_s, en minutes pour longest_recent_run.duration_min ; "
    "'semi' = 21.0975 km, 'marathon' = 42.195 km ; months_ago = ancienneté du chrono en mois ; "
    "goals parmi premier_10k, chrono, trail, voyage, finir.\nSchéma : "
)


def llm_prompt() -> str:
    """Consigne LLM (ou `audio_to_llm` de Gladia) avec le schéma JSON de `CoachProfile`."""
    schema = CoachProfile.model_json_schema(mode="validation")
    return _LLM_PROMPT + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def parse_llm_json(text: str) -> CoachProfile:
    """Valide la sortie du LLM (tolère un bloc ```json ... ```). Lève `ValueError` si invalide."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("pas d'objet JSON dans la réponse du LLM")
    data = json.loads(match.group(0))
    data.pop("missing_fields", None)
    return CoachProfile.model_validate(data)


_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60,
}  # fmt: skip
_NUM = r"(\d+(?:[.,]\d+)?)"
_DIST_WORDS = {"semi-marathon": 21.0975, "semi": 21.0975, "marathon": 42.195}
_CHRONO_HINT = r"(?:chrono|course|couru|fait|termin\w*|boucl\w*)"


def _normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(\d) (\d{3})\b", r"\1\2", t)
    for word, value in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{word}\b", str(value), t)
    t = re.sub(r"\b(\d+) et (\d+)\b", lambda m: str(int(m[1]) + int(m[2])), t)
    t = re.sub(r"\b(\d+)[- ](\d)\b", lambda m: str(int(m[1]) + int(m[2])) if int(m[1]) % 10 == 0 else m[0], t)
    t = re.sub(r"\b(\d+) et demi(e)?\b", lambda m: f"{m[1]}.5", t)
    return t.replace("kilomètres", "km").replace("kilometres", "km").replace("bornes", "km")


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _duration_s(text: str) -> float | None:
    m = re.search(rf"{_NUM}\s*h(?:eures?)?\s*(?:(\d{{1,2}})(?:\s*(?:min\w*|'))?)?", text)
    if m:
        return _num(m[1]) * 3600 + (int(m[2]) * 60 if m[2] else 0)
    m = re.search(rf"{_NUM}\s*(?:min\w*|')\s*(?:(\d{{1,2}})\s*(?:s\w*|\"))?", text)
    if m:
        return _num(m[1]) * 60 + (int(m[2]) if m[2] else 0)
    return None


def _distance_km(text: str) -> float | None:
    if re.search(r"\d+\s+\d+\s*km\b", text):
        return None  # « 14 10 km » : transcription ambiguë, la question sera reposée
    m = re.search(rf"{_NUM}\s*(?:km|k)\b", text)
    if m:
        return _num(m[1])
    for word, km in _DIST_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return km
    return None


def extract_rule_based(transcript: str) -> CoachProfile:
    """Parseur à règles (regex), sans LLM ; ne remplit que ce qui est dit."""
    t = _normalize(transcript)
    data: dict[str, Any] = {}
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+|\n", t) if s.strip()]

    m = re.search(rf"{_NUM}\s*(?:fois|sorties?|séances?|seances?)\s*(?:par|/|a la|à la)\s*semaine", t)
    if m:
        data["sessions_per_week"] = _num(m[1])
    m = re.search(rf"{_NUM}\s*km\s*(?:par|/|a la|à la)\s*semaine", t)
    if m is None:
        m = re.search(rf"(?:fois|sorties?|séances?) (?:par|/) semaine[^.]*?{_NUM}\s*km", t)
    if m:
        data["weekly_km"] = _num(m[1])

    for s in sentences:
        if "plus longue" in s or "sortie longue" in s:
            dist = _distance_km(s)
            if dist is not None:
                after = s.split(" en ", 1)[1] if " en " in s else ""
                duration_s = _duration_s(after)
                dplus = re.search(r"(\d+)\s*(?:m(?:ètres?)?\s*(?:de\s*)?(?:d\+|dénivelé|denivele))", s)
                data["longest_recent_run"] = RecentRun(
                    distance_km=dist,
                    duration_min=duration_s / 60 if duration_s else None,
                    d_plus_m=int(dplus[1]) if dplus else None,
                )
            continue
        if re.search(_CHRONO_HINT, s) and " en " in s and "semaine" not in s:
            dist = _distance_km(s)
            dur = _duration_s(s.split(" en ", 1)[1])
            if dist is not None and dur:
                months = 0.0
                ago = re.search(rf"(?:il y a|ça fait|ca fait)\s*{_NUM}\s*(mois|ans?|semaines?)", s)
                if ago:
                    factor = {"mois": 1, "an": 12, "ans": 12}.get(ago[2], 0.25)
                    months = _num(ago[1]) * factor
                elif "année dernière" in s or "l'an dernier" in s or "annee derniere" in s:
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
    m = re.search(rf"(?:j'ai|âgée? de|agee? de)\s*{_NUM}\s*ans\b", t)
    if m and 8 <= _num(m[1]) <= 100:
        data["age"] = int(_num(m[1]))
    m = re.search(rf"(?:depuis|ça fait|ca fait)\s*{_NUM}\s*(mois|ans?)\s*(?:que je cours|de course)?", t)
    if m and ("cour" in t[m.start() : m.end() + 25] or "depuis" in m[0]):
        data["running_since_months"] = int(_num(m[1]) * (1 if m[2] == "mois" else 12))

    goals = []
    if re.search(r"premier 10|1er 10|premier dix", t):
        goals.append(Goal.premier_10k)
    if re.search(r"chrono|record|battre|sous les", t) and "pas de chrono" not in t:
        goals.append(Goal.chrono)
    if "trail" in t:
        goals.append(Goal.trail)
    if re.search(r"voyage|étranger|etranger|week-end", t):
        goals.append(Goal.voyage)
    if re.search(r"\bfinir\b|terminer", t):
        goals.append(Goal.finir)
    data["goals"] = goals
    return CoachProfile(**data)


class PlausibilityIssue(BaseModel):
    field: str
    message: str


def plausibility_issues(p: CoachProfile) -> list[PlausibilityIssue]:
    """Champs incohérents (erreur de transcription ou de LLM) : à remettre à `None` et à reposer."""
    issues: list[PlausibilityIssue] = []
    run = p.longest_recent_run
    if run is not None and run.duration_min:
        pace = run.duration_min / run.distance_km
        if not 2.5 <= pace <= 12:
            issues.append(
                PlausibilityIssue(
                    field="longest_recent_run",
                    message=f"{run.distance_km:g} km en {run.duration_min:g} min ({pace:.1f} min/km)",
                )
            )
    if run is not None and p.weekly_km and run.distance_km > max(p.weekly_km, 10) * 1.2:
        issues.append(
            PlausibilityIssue(
                field="longest_recent_run",
                message=f"{run.distance_km:g} km > volume hebdo {p.weekly_km:g} km",
            )
        )
    race = p.recent_race
    if race is not None:
        pace = race.time_s / 60 / race.distance_km
        if not 2.6 <= pace <= 12:
            issues.append(
                PlausibilityIssue(
                    field="recent_race",
                    message=f"{race.distance_km:g} km en {race.time_s} s ({pace:.1f} min/km)",
                )
            )
    if p.sessions_per_week and p.weekly_km and p.weekly_km / p.sessions_per_week > 40:
        issues.append(PlausibilityIssue(field="weekly_km", message="plus de 40 km par sortie"))
    return issues


class ProfileExtraction(BaseModel):
    """Profil nettoyé + ce qu'il faut redemander au coureur."""

    profile: CoachProfile
    method: Literal["llm", "regles"]
    issues: list[PlausibilityIssue] = Field(default_factory=list)
    cleared_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    llm_error: str | None = None


def extract_profile(text: str, llm_json: str | None = None) -> ProfileExtraction:
    """Transcription (et sortie LLM facultative) -> `CoachProfile` vérifié.

    Avec `llm_json` (réponse du LLM à `llm_prompt()` + transcription), on l'utilise ; s'il est
    invalide, on retombe sur le parseur à règles. Les champs invraisemblables sont remis à `None`.
    `follow_up_questions` liste les questions de `QUESTIONS` à reposer pour ces champs effacés ;
    les champs simplement non dits sont dans `profile.missing_fields` (« je ne sais pas » est valide).
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
