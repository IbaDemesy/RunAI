"""Consignes envoyées aux agents et actions laissées à l'humain au portail."""

import re
from datetime import date

from pydantic import BaseModel, Field

from runai.app.providers import FORBIDDEN_ACCOMMODATION_SITES
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

ASK_USER_RULES = (
    "Ne redemande jamais une information déjà donnée ci-dessus (dates, budget, ville "
    "de départ, distance, mode de transport). Utilise ask_user uniquement pour un choix "
    "qui dépend du site (sas, taille de t-shirt, hôtel parmi plusieurs offres, horaire, "
    "tarif) ; pose au plus 2 questions."
)
STOP_RULES = (
    "Arrête-toi avant tout paiement, réservation, soumission définitive ou "
    "consentement. Ne contourne jamais un captcha ni une protection anti-bot ; "
    "si tu es bloqué, arrête-toi et résume clairement en commençant par "
    "« BLOCAGE CAPTCHA/ANTI-BOT », avec l'URL et l'étape atteintes."
)
_AMOUNT = r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{1,2})?"
_CURRENCY_AMOUNT = re.compile(rf"(?P<amount>{_AMOUNT})\s*(?:€|EUR|euros?)", re.IGNORECASE)
_BUDGET_AMOUNT = re.compile(
    rf"(?:budget(?:\s+max(?:imum)?)?|max(?:imum)?)\D{{0,24}}(?P<amount>{_AMOUNT})",
    re.IGNORECASE,
)
_BARE_AMOUNT = re.compile(rf"^\s*(?P<amount>{_AMOUNT})\s*$")
_TOTAL_BUDGET = re.compile(
    r"\btotal\b|\bpour\s+(?:les\s+)?(?:2|deux)\s+nuits\b", re.IGNORECASE
)
_PER_NIGHT_BUDGET = re.compile(
    r"\bpar\s+nuit\b|/\s*nuit\b|\bper\s+night\b", re.IGNORECASE
)


def extract_budget_per_night(
    text: str, *, require_context: bool = False, nights: int = 2
) -> float | None:
    search_text = text
    if require_context:
        context = re.search(
            r"\b(?:budget|h[oô]tel|par\s+nuit|per\s+night)\b", text, re.IGNORECASE
        )
        if not context:
            return None
        search_text = text[context.start() :]
    match = (
        _CURRENCY_AMOUNT.search(search_text)
        or _BUDGET_AMOUNT.search(search_text)
        or _BARE_AMOUNT.fullmatch(search_text)
    )
    if not match:
        return None
    amount = match.group("amount").replace(" ", "")
    if "," in amount and "." in amount:
        amount = amount.replace(".", "").replace(",", ".")
    elif "," in amount:
        amount = amount.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", amount):
        amount = amount.replace(".", "")
    budget = float(amount)
    if _TOTAL_BUDGET.search(text) and not _PER_NIGHT_BUDGET.search(text):
        budget /= max(nights, 1)
    return budget


def human_action(stop_point: StopPoint | None) -> str:
    if stop_point is None:
        return "Rien n'a été engagé : reprenez la main depuis la vue live si besoin."
    return HUMAN_ACTIONS[stop_point]


def _profile_lines(profile: RunnerProfile) -> str:
    text = (
        f"Profil fictif : {profile.first_name} {profile.last_name}, {profile.email}, "
        f"né(e) le {profile.birth_date.isoformat()}, sexe {profile.gender}, "
        f"nationalité {profile.nationality}, ville {profile.city}."
    )
    if not profile.fictional:
        text = (
            f"Runner profile: {profile.first_name} {profile.last_name}, {profile.email}, "
            f"born {profile.birth_date.isoformat()}, gender {profile.gender}, "
            f"nationality {profile.nationality}, city {profile.city}."
        )
    for field in ("phone", "emergency_contact_name", "emergency_contact_phone",
                  "license_number", "tshirt_size", "estimated_finish_time"):
        if value := getattr(profile, field):
            text += f" {field.replace('_', ' ')}: {value}."
    return text


class TripBrief(BaseModel):
    """Données confirmées par l'humain ou sourcées ; None = inconnu, l'agent doit demander."""

    race_label: str
    city: str
    country: str
    race_date: date | None = None
    distance_km: float | None = None
    arrival: date | None = None
    departure: date | None = None
    nights: int | None = None
    origin: str | None = None
    budget_total_eur: float | None = None
    budget_per_night_eur: float | None = None
    budget_open: bool = False
    transport_mode: str | None = None
    preferences: str | None = None
    hotel_landmarks: list[str] = Field(default_factory=list)
    health_question: str | None = None
    registration_platform: str | None = None
    accommodation_site: str | None = None
    accommodation_url: str | None = None
    transport_site: str | None = None
    transport_url: str | None = None


DEFAULT_HEALTH_QUESTION = (
    "Avez-vous le certificat médical, la licence ou le justificatif de santé exigé "
    "par l'organisateur ?"
)
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_TRANSPORT_LABELS = {"train": "train", "flight": "avion", "bus": "bus", "car": "voiture"}


def fr_date(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _km(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def brief_from_race(race: Race, query: str = "") -> TripBrief:
    """Brief minimal tiré d'une fiche course seule : tout le reste est inconnu."""
    label = race.name
    if race.race_date and str(race.race_date.year) not in label:
        label = f"{label} {race.race_date.year}"
    return TripBrief(
        race_label=label,
        city=race.city,
        country=race.country,
        race_date=race.race_date,
        distance_km=race.distance_km,
        budget_per_night_eur=extract_budget_per_night(query, require_context=True),
        hotel_landmarks=[x for x in (race.start_location, race.bib_pickup) if x],
    )


def _registration_task(race: Race, brief: TripBrief, profile: RunnerProfile) -> str:
    platform = brief.registration_platform or "la plateforme officielle"
    url = race.registration_url or "le lien officiel fourni par la recherche"
    distance = brief.distance_km or race.distance_km
    distance_text = (
        f" ({_km(distance)} km)"
        if distance
        else " (distance inconnue : demande-la avec ask_user avant de choisir)"
    )
    return (
        f"Prépare l'inscription à {brief.race_label} sur {platform}, "
        f"à partir du lien officiel fourni : {url}{distance_text}. "
        f"N'utilise jamais Klikego ni un revendeur ; si le lien fourni n'est pas sur "
        f"{platform}, arrête-toi et signale que le lien officiel manque. "
        "Continue en invité. Utilise uniquement le profil fictif ci-dessous et "
        "remplis seulement les champs nécessaires. Si l'inscription en invité "
        "n'est pas possible, arrête-toi avant toute création de compte. "
        "Ne pose aucune question de santé : le certificat médical ou le PPS sera fourni "
        "par l'utilisateur lui-même. "
        "Ne coche aucune case de santé, ne fournis aucun numéro et ne téléverse aucun "
        "document ; arrête-toi à la déclaration de santé si elle apparaît, sinon au "
        f"paiement. {_profile_lines(profile)} {ASK_USER_RULES} {STOP_RULES}"
    )


def _stay_text(brief: TripBrief) -> str:
    if brief.arrival and brief.departure:
        nights = brief.nights or (brief.departure - brief.arrival).days
        return (
            f"arrivée le {fr_date(brief.arrival)} et départ le "
            f"{fr_date(brief.departure)} ({nights} nuits)"
        )
    return (
        "dates de séjour inconnues : demande d'abord avec ask_user les dates "
        "d'arrivée et de départ, n'invente aucune date"
    )


def _budget_text(brief: TripBrief, nights: int | None) -> str:
    stay = f"les {nights} nuits" if nights else "le séjour"
    if brief.budget_open:
        return (
            "Pas de plafond de budget : propose les meilleures options qualité-prix "
            "et donne leur prix."
        )
    if brief.budget_per_night_eur is not None:
        per_night = brief.budget_per_night_eur
        total = f", soit {per_night * nights:g} € maximum pour {stay}" if nights else ""
        return (
            f"Budget maximal déjà donné : {per_night:g} € par nuit{total}. "
            "Respecte strictement ce plafond."
        )
    if brief.budget_total_eur is not None:
        return (
            f"Budget total du voyage déjà donné : {brief.budget_total_eur:g} € tous "
            f"postes confondus ; le total pour {stay} ne doit jamais dépasser ce montant. "
            "Signale le montant restant pour les autres postes."
        )
    return (
        "Avant toute recherche, demande avec ask_user : « Budget max par nuit ? » "
        "avec les options « 100 € », « 150 € », « 200 € ». Attends la réponse avant "
        "d'ouvrir le site."
    )


def _accommodation_task(brief: TripBrief) -> str:
    if not brief.accommodation_site:
        raise ValueError("Hébergement non automatisé : aucun site officiel autorisé.")
    nights = brief.nights
    if nights is None and brief.arrival and brief.departure:
        nights = (brief.departure - brief.arrival).days
    near = (
        f"près de : {' ; '.join(brief.hotel_landmarks)}"
        if brief.hotel_landmarks
        else "au plus près du départ de la course"
    )
    price_tag = f"PRIX_TOTAL_{nights}_NUITS" if nights else "PRIX_TOTAL_SEJOUR"
    site = brief.accommodation_site
    if brief.accommodation_url:
        site = f"{site} ({brief.accommodation_url})"
    preferences = (
        f"Préférences de l'utilisateur : {brief.preferences}. " if brief.preferences else ""
    )
    return (
        f"Trouve un hôtel à {brief.city} ({brief.country}) pour 1 adulte, "
        f"{_stay_text(brief)}, {near}. {_budget_text(brief, nights)} {preferences}"
        f"Va exclusivement sur le {site} ; "
        f"{', '.join(FORBIDDEN_ACCOMMODATION_SITES)} et tout autre agrégateur sont "
        "interdits. Compare les offres disponibles et ne choisis qu'un tarif dont le "
        "total respecte le plafond. Si aucune offre ne respecte le budget, ne la "
        "présente pas comme convenable et indique qu'aucune option abordable n'a été "
        "trouvée. Arrête-toi au récapitulatif avant paiement, sans réserver. Affiche "
        "les prix en euros si le site le permet. Dans la réponse finale, donne le prix "
        f"total exact sous la forme {price_tag}: 123.45 EUR ; si le total est absent, "
        f"écris {price_tag}: INCONNU. {ASK_USER_RULES} {STOP_RULES}"
    )


def _transport_task(brief: TripBrief) -> str:
    if not brief.transport_site:
        raise ValueError("Transport non automatisé : aucun vendeur officiel validé.")
    mode = _TRANSPORT_LABELS.get(brief.transport_mode or "", brief.transport_mode or "")
    mode_text = f" en {mode}" if mode else ""
    origin = brief.origin or "(ville de départ inconnue : demande-la avec ask_user)"
    dates = (
        f"aller le {fr_date(brief.arrival)} et retour le {fr_date(brief.departure)}"
        if brief.arrival and brief.departure
        else "dates inconnues : demande-les avec ask_user, n'en invente aucune"
    )
    site = brief.transport_site
    if brief.transport_url and brief.transport_url.split("//")[-1] not in site:
        site = f"{site} ({brief.transport_url})"
    return (
        f"Cherche un aller-retour{mode_text} {origin} → {brief.city} sur {site} pour "
        f"1 adulte : {dates}. N'utilise aucun autre vendeur et jamais TAP. Si "
        "plusieurs horaires ou tarifs sont possibles, demande à l'utilisateur de "
        f"choisir ; ne devine pas. {ASK_USER_RULES} {STOP_RULES}"
    )


def build_task(
    kind: StepKind,
    race: Race,
    profile: RunnerProfile,
    *,
    brief: TripBrief,
) -> str:
    """Consigne H d'une étape à partir du cadrage confirmé."""
    if kind is StepKind.registration:
        task = _registration_task(race, brief, profile)
    elif kind is StepKind.accommodation:
        task = _accommodation_task(brief)
    elif kind is StepKind.transport:
        task = _transport_task(brief)
    else:
        raise ValueError(f"Pas d'agent de navigation pour l'étape {kind.value}")
    return guard_task(task)
