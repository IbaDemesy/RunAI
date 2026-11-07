"""« Feu vert règlement » : éligibilité (documents, âge, clôture) et réalisme de l'objectif face aux barrières."""

from datetime import date, timedelta

from runai.logistics.durations import format_duration
from runai.logistics.models import (
    Eligibility,
    EntryPath,
    HumanTodo,
    Light,
    RaceRules,
    Reason,
    RequirementKind,
    RunnerGoal,
    RunnerSituation,
)
from runai.models import RunnerProfile

GREEN_MARGIN = 0.10
AMBITIOUS_MARGIN = 0.10
RIEGEL_EXPONENT = 1.06
_ORDER = {Light.green: 0, Light.orange: 1, Light.red: 2}

ELIGIBILITY_FIELDS = ("race_date", "time_limit")


def eligibility(
    rules: RaceRules,
    profile: RunnerProfile | None = None,
    situation: RunnerSituation | None = None,
    goal: RunnerGoal | None = None,
    *,
    today: date | None = None,
) -> Eligibility:
    """Feu vert / orange / rouge, avec raisons sourcées et pièces que l'humain doit fournir lui-même.

    - rouge : inscription impossible (clos, trop jeune, aucune voie) ou objectif plus lent que la barrière ;
    - orange : faisable mais à préparer (certificat avec examens, marge < 10 %, règle introuvable) ;
    - vert : rien de bloquant. Les marges sont des estimations (allure régulière, formule de Riegel).
    """
    profile = profile or RunnerProfile()
    situation = situation or RunnerSituation(residence_country=profile.nationality)
    today = today or date.today()
    reasons: list[Reason] = []

    if rules.registration_deadline and today > rules.registration_deadline.date():
        reasons.append(
            Reason(
                level=Light.red,
                code="registration_closed",
                message=f"Inscriptions closes depuis le {rules.registration_deadline:%d/%m/%Y}.",
                source_url=rules.source_url("registration_deadline"),
            )
        )
    if rules.min_age and rules.race_date and rules.race_date.year - profile.birth_date.year < rules.min_age:
        reasons.append(
            Reason(
                level=Light.red,
                code="too_young",
                message=f"Âge minimum {rules.min_age} ans dans l'année de la course.",
                source_url=rules.source_url("min_age"),
            )
        )

    path, alternative = choose_entry_path(rules, profile, situation)
    reasons += _document_reasons(rules, path, alternative, situation)
    todos = _todos(path) if path else []
    if not rules.entry_paths:
        todos.append(
            HumanTodo(
                kind=RequirementKind.other,
                label="Vérifier dans le règlement les documents exigés (licence, certificat, PPS)",
                source_url=str(rules.regulation_url) if rules.regulation_url else None,
            )
        )
    if goal:
        reasons += _realism_reasons(rules, goal)
    unknown = [field for field in ELIGIBILITY_FIELDS if field in rules.missing_fields]
    if unknown:
        reasons.append(
            Reason(
                level=Light.orange,
                code="rules_incomplete",
                message="Non trouvé dans le règlement : " + ", ".join(unknown) + ". À confirmer avant de s'inscrire.",
                source_url=str(rules.regulation_url) if rules.regulation_url else None,
            )
        )

    light = max((reason.level for reason in reasons), key=_ORDER.__getitem__, default=Light.orange)
    return Eligibility(
        light=light,
        reasons=reasons,
        human_todo=todos,
        entry_path_id=path.id if path else None,
        alternative_path_id=alternative.id if alternative else None,
    )


def choose_entry_path(
    rules: RaceRules, profile: RunnerProfile, situation: RunnerSituation
) -> tuple[EntryPath | None, EntryPath | None]:
    """Voie d'inscription qui correspond au coureur, et voie non compétitive de repli si elle existe."""
    host = (rules.country_code or "").upper()
    citizen = profile.nationality.upper() == host if host else None
    resident = situation.residence_country.upper() == host if host else None

    def matches(path: EntryPath) -> bool:
        return (
            (path.host_citizen is None or citizen is None or path.host_citizen == citizen)
            and (path.resident_in_host_country is None or resident is None or path.resident_in_host_country == resident)
            and (path.licenses is None or situation.license in path.licenses)
        )

    candidates = [path for path in rules.entry_paths if matches(path)]
    wanted = [path for path in candidates if path.competitive == situation.wants_competitive]
    path = (wanted or candidates or [None])[0]
    alternative = None
    if path and path.competitive:
        alternative = next((other for other in candidates if not other.competitive), None)
    return path, alternative


def riegel(distance_km: float, time: timedelta, target_km: float) -> timedelta:
    """Temps prédit sur `target_km` à partir d'un résultat récent (Riegel, exposant 1,06) : une estimation."""
    return time * (target_km / distance_km) ** RIEGEL_EXPONENT


def _document_reasons(
    rules: RaceRules, path: EntryPath | None, alternative: EntryPath | None, situation: RunnerSituation
) -> list[Reason]:
    source = rules.source_url("entry_paths") or (str(rules.regulation_url) if rules.regulation_url else None)
    if not rules.entry_paths:
        return [
            Reason(
                level=Light.orange,
                code="entry_rules_unknown",
                message="Conditions de participation non trouvées dans le règlement : à vérifier avant de s'inscrire.",
                source_url=source,
            )
        ]
    if path is None:
        return [
            Reason(
                level=Light.red,
                code="no_entry_path",
                message="Aucune voie d'inscription du règlement ne correspond à votre situation.",
                source_url=source,
            )
        ]
    path_source = str(path.source.url) if path.source else source
    certificate = next((r for r in path.requirements if r.kind is RequirementKind.medical_certificate), None)
    if certificate and not situation.has_valid_medical_certificate:
        message = f"Voie « {path.label} » : {certificate.label}."
        if certificate.detail:
            message += f" {certificate.detail}"
        if alternative:
            limits = " ; ".join(alternative.limitations)
            message += f" Repli possible sans certificat : « {alternative.label} »" + (f" ({limits})." if limits else ".")
        cert_source = str(certificate.source.url) if certificate.source else path_source
        return [Reason(level=Light.orange, code="medical_certificate", message=message, source_url=cert_source)]
    message = f"Voie « {path.label} » : pièces à fournir par vous, rien de bloquant."
    if path.limitations:
        message += " " + " ; ".join(path.limitations) + "."
    return [Reason(level=Light.green, code="documents", message=message, source_url=path_source)]


def _todos(path: EntryPath) -> list[HumanTodo]:
    fallback = str(path.source.url) if path.source else None
    return [
        HumanTodo(
            kind=requirement.kind,
            label=requirement.label,
            detail=requirement.detail,
            cost_eur=requirement.cost_eur,
            deadline=requirement.deadline,
            source_url=str(requirement.source.url) if requirement.source else fallback,
        )
        for requirement in path.requirements
    ]


def _realism_reasons(rules: RaceRules, goal: RunnerGoal) -> list[Reason]:
    distance = rules.distance_km
    if distance and abs(goal.distance_km - distance) / distance > 0.02:
        return [
            Reason(
                level=Light.orange,
                code="goal_distance_mismatch",
                message=f"Objectif donné pour {goal.distance_km:g} km, course de {distance:g} km : réalisme non évalué.",
            )
        ]
    distance = distance or goal.distance_km
    target = goal.target_high or goal.target_low
    predicted = riegel(goal.recent_result.distance_km, goal.recent_result.time, distance) if goal.recent_result else None
    if target is None and predicted is None:
        return []
    reasons: list[Reason] = []
    if rules.time_limit is None:
        reasons.append(
            Reason(
                level=Light.orange,
                code="time_limit_unknown",
                message="Temps limite non trouvé dans le règlement : réalisme à confirmer.",
                source_url=str(rules.regulation_url) if rules.regulation_url else None,
            )
        )
        if not rules.time_gates:
            return reasons
    limit_source = rules.source_url("time_limit")
    gates_source = rules.source_url("time_gates") or limit_source
    for label, expected in (("Objectif", target), ("Temps prédit (Riegel)", predicted)):
        if expected is None:
            continue
        code = "goal" if label == "Objectif" else "prediction"
        if rules.time_limit is not None:
            reasons.append(
                _compare(f"{label} {format_duration(expected)}", expected, rules.time_limit, code, limit_source)
            )
        for gate in rules.time_gates:
            at_gate = expected * (gate.km / distance)
            reasons.append(
                _compare(
                    f"{label} au km {_km(gate.km)} ≈ {format_duration(at_gate)} (allure régulière)",
                    at_gate,
                    gate.max_elapsed,
                    f"{code}_gate_{gate.km:g}",
                    gates_source,
                )
            )
    if target and predicted and target < predicted * (1 - AMBITIOUS_MARGIN):
        reasons.append(
            Reason(
                level=Light.orange,
                code="ambitious_goal",
                message=(
                    f"Objectif {format_duration(target)} plus de {AMBITIOUS_MARGIN:.0%} plus rapide que le temps "
                    f"prédit d'après votre résultat récent ({format_duration(predicted)})."
                ),
            )
        )
    return reasons


def _compare(label: str, expected: timedelta, limit: timedelta, code: str, source: str | None) -> Reason:
    margin = limit - expected
    if margin < timedelta(0):
        level, verdict = Light.red, f"au-delà de la barrière de {format_duration(limit)}"
    elif margin < limit * GREEN_MARGIN:
        level, verdict = Light.orange, f"marge de {format_duration(margin)} seulement sur la barrière de {format_duration(limit)}"
    else:
        level, verdict = Light.green, f"marge de {format_duration(margin)} sur la barrière de {format_duration(limit)}"
    return Reason(level=level, code=code, message=f"{label} : {verdict}.", source_url=source)


def _km(value: float) -> str:
    return f"{value:g}".replace(".", ",")
