"""Questions vocales 'Quel coureur es-tu ?' et extraction des reponses en RunnerProfile.

Chaine visee : Gladia (live STT, ou pre-enregistre + audio_to_llm) -> LLM avec le
schema JSON de RunnerProfile -> validation Pydantic. Le parseur a regles ci-dessous
sert de secours (pas de LLM) et de garde-fou : il ne remplit que ce qui est dit.
"""

from __future__ import annotations

import json
import re

from runner_level import Goal, RecentRace, RecentRun, RunnerProfile

QUESTIONS = [
    "Combien de fois cours-tu par semaine en ce moment, et a peu pres combien de kilometres ?",
    "Quelle a ete ta plus longue sortie ces dernieres semaines : distance, et en combien de temps ?",
    "As-tu un chrono recent sur une course, 5 km, 10 km, semi ou marathon ? Si oui, lequel et quand ?",
    "Depuis combien de temps cours-tu, et quel age as-tu ?",
    "Qu'est-ce qui te fait envie : un premier 10 km, battre un chrono, du trail, ou courir en voyage ?",
]

CUSTOM_VOCABULARY = ["semi", "marathon", "trail", "D+", "dénivelé", "Cooper", "chrono", "10 km", "VMA"]

LLM_PROMPT = (
    "Tu extrais le profil d'un coureur a partir de la transcription de ses reponses. "
    "Reponds UNIQUEMENT par un objet JSON valide conforme a ce schema JSON. "
    "Regles : une information non dite vaut null (ou [] pour goals), ne jamais deviner ni inventer ; "
    "temps en secondes pour recent_race.time_s, en minutes pour longest_recent_run.duration_min ; "
    "'semi' = 21.0975 km, 'marathon' = 42.195 km ; months_ago = anciennete du chrono en mois ; "
    "goals parmi premier_10k, chrono, trail, voyage, finir.\nSchema : "
)


def llm_prompt() -> str:
    schema = RunnerProfile.model_json_schema(mode="validation")
    return LLM_PROMPT + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def parse_llm_json(text: str) -> RunnerProfile:
    """Valide la sortie du LLM (tolere un bloc ```json ... ```)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("pas d'objet JSON dans la reponse du LLM")
    return RunnerProfile.model_validate_json(match.group(0))


NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60,
}
NUM = r"(\d+(?:[.,]\d+)?)"
DIST_WORDS = {"semi": 21.0975, "semi-marathon": 21.0975, "marathon": 42.195}
CHRONO_HINT = r"(?:chrono|course|couru|fait|termin\w*|boucl\w*)"


def _normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(\d) (\d{3})\b", r"\1\2", t)
    for word, value in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{word}\b", str(value), t)
    t = re.sub(r"\b(\d+) et (\d+)\b", lambda m: str(int(m[1]) + int(m[2])), t)
    t = re.sub(r"\b(\d+)[- ](\d)\b", lambda m: str(int(m[1]) + int(m[2])) if int(m[1]) % 10 == 0 else m[0], t)
    t = re.sub(r"\b(\d+) et demi(e)?\b", lambda m: f"{m[1]}.5", t)
    t = t.replace("kilomètres", "km").replace("kilometres", "km").replace("bornes", "km")
    return t


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _duration_s(text: str) -> float | None:
    m = re.search(rf"{NUM}\s*h(?:eures?)?\s*(?:(\d{{1,2}})(?:\s*(?:min\w*|'))?)?", text)
    if m:
        return _num(m[1]) * 3600 + (int(m[2]) * 60 if m[2] else 0)
    m = re.search(rf"{NUM}\s*(?:min\w*|')\s*(?:(\d{{1,2}})\s*(?:s\w*|\"))?", text)
    if m:
        return _num(m[1]) * 60 + (int(m[2]) if m[2] else 0)
    return None


def _distance_km(text: str) -> float | None:
    if re.search(r"\d+\s+\d+\s*km\b", text):
        return None  # "14 10 km" : transcription ambigue, on reposera la question
    m = re.search(rf"{NUM}\s*(?:km|k)\b", text)
    if m:
        return _num(m[1])
    for word, km in DIST_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return km
    return None


def extract_rule_based(transcript: str) -> RunnerProfile:
    t = _normalize(transcript)
    data: dict = {}
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+|\n", t) if s.strip()]

    m = re.search(rf"{NUM}\s*(?:fois|sorties?|séances?|seances?)\s*(?:par|/|a la|à la)\s*semaine", t)
    if m:
        data["sessions_per_week"] = _num(m[1])
    m = re.search(rf"{NUM}\s*km\s*(?:par|/|a la|à la)\s*semaine", t)
    if m is None:
        m = re.search(rf"(?:fois|sorties?|séances?) (?:par|/) semaine[^.]*?{NUM}\s*km", t)
    if m:
        data["weekly_km"] = _num(m[1])

    for s in sentences:
        if "plus longue" in s or "sortie longue" in s:
            dist = _distance_km(s)
            if dist is not None:
                after = s.split("en", 1)[1] if " en " in s else ""
                data["longest_recent_run"] = RecentRun(distance_km=dist, duration_min=(_duration_s(after) or 0) / 60 or None)
                dplus = re.search(r"(\d+)\s*(?:m(?:ètres?)?\s*(?:de\s*)?(?:d\+|dénivelé|denivele))", s)
                if dplus:
                    data["longest_recent_run"].d_plus_m = int(dplus[1])
            continue
        if re.search(CHRONO_HINT, s) and " en " in s and "semaine" not in s:
            dist = _distance_km(s)
            dur = _duration_s(s.split(" en ", 1)[1])
            if dist is not None and dur:
                months = 0.0
                ago = re.search(rf"(?:il y a|ça fait|ca fait)\s*{NUM}\s*(mois|ans?|semaines?)", s)
                if ago:
                    factor = {"mois": 1, "an": 12, "ans": 12}.get(ago[2], 0.25)
                    months = _num(ago[1]) * factor
                elif "année dernière" in s or "l'an dernier" in s or "annee derniere" in s:
                    months = 12
                data["recent_race"] = RecentRace(distance_km=dist, time_s=int(dur), months_ago=months)

    m = re.search(rf"cooper.*?{NUM}\s*(?:m\b|mètres|metres)", t) or re.search(rf"{NUM}\s*(?:m\b|mètres|metres).*?cooper", t)
    if m:
        data["cooper_m"] = int(_num(m[1]))
    m = re.search(rf"(?:j'ai|âgée? de|agee? de)\s*{NUM}\s*ans\b", t)
    if m:
        data["age"] = int(_num(m[1]))
    m = re.search(rf"(?:depuis|ça fait|ca fait)\s*{NUM}\s*(mois|ans?)\s*(?:que je cours|de course)?", t)
    if m and ("cour" in t[m.start():m.end() + 25] or "depuis" in m[0]):
        data["running_since_months"] = int(_num(m[1]) * (1 if m[2] == "mois" else 12))

    goals = []
    if re.search(r"premier 10|1er 10|premier dix", t):
        goals.append(Goal.premier_10k)
    if re.search(r"chrono|record|battre|sous les", t) and "pas de chrono" not in t:
        goals.append(Goal.chrono)
    if "trail" in t:
        goals.append(Goal.trail)
    if re.search(r"voyage|étranger|etranger|à l'étranger|week-end", t):
        goals.append(Goal.voyage)
    if re.search(r"\bfinir\b|terminer", t):
        goals.append(Goal.finir)
    data["goals"] = goals
    return RunnerProfile(**data)


def plausibility_issues(p: RunnerProfile) -> list[str]:
    """Champs incoherents (erreur STT ou LLM) : a remettre a null et a reposer a la voix."""
    issues = []
    run = p.longest_recent_run
    if run is not None and run.duration_min:
        pace = run.duration_min / run.distance_km
        if not 2.5 <= pace <= 12:
            issues.append(f"longest_recent_run : {run.distance_km:g} km en {run.duration_min:g} min ({pace:.1f} min/km)")
    if run is not None and p.weekly_km and run.distance_km > max(p.weekly_km, 10) * 1.2:
        issues.append(f"longest_recent_run : {run.distance_km:g} km > volume hebdo {p.weekly_km:g} km")
    race = p.recent_race
    if race is not None:
        pace = race.time_s / 60 / race.distance_km
        if not 2.6 <= pace <= 12:
            issues.append(f"recent_race : {race.distance_km:g} km en {race.time_s} s ({pace:.1f} min/km)")
    if p.sessions_per_week and p.weekly_km and p.weekly_km / p.sessions_per_week > 40:
        issues.append("weekly_km : plus de 40 km par sortie")
    return issues
