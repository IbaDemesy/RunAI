"""Consignes envoyées aux agents et actions laissées à l'humain au portail."""

from datetime import timedelta

from runai.models import Race, RunnerProfile, StepKind, StopPoint
from runai.safety import guard_task

STEP_LABELS: dict[StepKind, str] = {
    StepKind.search: "Recherche",
    StepKind.registration: "Inscription",
    StepKind.accommodation: "Hébergement",
    StepKind.transport: "Transport",
}

HUMAN_ACTIONS: dict[StopPoint, str] = {
    StopPoint.payment: "Vérifiez le récapitulatif et le prix, puis payez vous-même sur le site officiel.",
    StopPoint.account_creation: "Créez vous-même votre compte : l'agent ne saisit jamais de mot de passe.",
    StopPoint.health_declaration: "Fournissez vous-même le certificat médical ou le PPS : aucune donnée de santé ne passe par l'agent.",
    StopPoint.consent: "Lisez et cochez vous-même le règlement, les CGU ou le consentement.",
    StopPoint.submission: "Relisez les champs pré-remplis et validez vous-même l'envoi définitif.",
}

EXCLUDED_SITES = "N'utilise ni Booking.com ni TAP (flytap.com)."


def human_action(stop_point: StopPoint | None) -> str:
    if stop_point is None:
        return "Rien n'a été engagé : reprenez la main depuis la vue live si besoin."
    return HUMAN_ACTIONS[stop_point]


def _profile_lines(profile: RunnerProfile) -> str:
    return (
        f"Profil fictif : {profile.first_name} {profile.last_name}, {profile.email}, "
        f"né(e) le {profile.birth_date.isoformat()}, sexe {profile.gender}, "
        f"nationalité {profile.nationality}, ville {profile.city}."
    )


def build_task(kind: StepKind, race: Race, profile: RunnerProfile) -> str:
    when = race.race_date.isoformat() if race.race_date else "date à confirmer"
    if kind is StepKind.registration:
        url = race.registration_url or "la page officielle d'inscription"
        distance = f" ({race.distance_km:g} km)" if race.distance_km else ""
        task = (
            f"Ouvre {url} et prépare l'inscription à {race.name}{distance} du {when}. "
            f"{_profile_lines(profile)} Remplis uniquement les champs avec ce profil."
        )
    elif kind is StepKind.accommodation:
        night = (
            (race.race_date - timedelta(days=1)).isoformat()
            if race.race_date
            else "la veille"
        )
        near = race.start_location or race.city
        task = (
            f"Trouve un hôtel à {race.city} près de {near} pour 1 adulte, arrivée le {night}, "
            f"départ le {when}. Choisis l'offre la plus proche du départ avec annulation gratuite "
            f"si possible. {EXCLUDED_SITES} {_profile_lines(profile)}"
        )
    elif kind is StepKind.transport:
        task = (
            f"Trouve un aller-retour {profile.city} → {race.city} pour 1 adulte, arrivée au plus "
            f"tard la veille du {when}, retour après la course. {EXCLUDED_SITES} "
            f"{_profile_lines(profile)}"
        )
    else:
        raise ValueError(f"Pas d'agent de navigation pour l'étape {kind.value}")
    return guard_task(task)
