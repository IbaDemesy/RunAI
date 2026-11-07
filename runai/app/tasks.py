"""Consignes envoyées aux agents et actions laissées à l'humain au portail."""

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from runai.models import Race, RunnerProfile, StepKind, StopPoint
from runai.safety import guard_task

if TYPE_CHECKING:
    from runai.app.scoping import Scope

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
    "Si une information manque ou qu'il faut choisir entre plusieurs options "
    "(distance, sas, taille de t-shirt, hôtel, horaire, tarif), appelle l'outil "
    "ask_user au lieu de deviner ; pose au plus 2 questions."
)
STOP_RULES = (
    "Arrête-toi avant tout paiement, réservation, soumission définitive ou "
    "consentement. Ne contourne jamais un captcha ni une protection anti-bot ; "
    "si tu es bloqué, arrête-toi et résume clairement en commençant par "
    "« BLOCAGE CAPTCHA/ANTI-BOT », avec l'URL et l'étape atteintes."
)
_AMOUNT = r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{1,2})?"
_CURRENCY_AMOUNT = re.compile(
    rf"(?P<amount>{_AMOUNT})\s*(?:€|EUR|euros?)", re.IGNORECASE
)
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
    text: str, *, require_context: bool = False
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
        budget /= 2
    return budget


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


_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _fr_date(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


DEPARTURE = re.compile(
    r"\b(?:je pars d[e']|je partirai d[e']|départ d[e']|au départ d[e']|depuis)\s*"
    r"(?P<city>[^,.;!?\n]{2,40}?)"
    r"(?=\s+(?:et|avec|pour|mais|ou|à|au|vers|demain|ce|cette)\b"
    r"|\s+(?:en|le|la|les)\b(?!\s+(?-i:[A-ZÀ-Ý]))|\s*[,.;!?\n]|\s*$)",
    re.IGNORECASE,
)


def extract_departure_city(text: str) -> str | None:
    match = DEPARTURE.search(text)
    return match.group("city").strip() if match else None


def stay_dates(race: Race) -> tuple[date, date] | None:
    if race.race_date is None:
        return None
    return race.race_date - timedelta(days=1), race.race_date + timedelta(days=1)


def _race_label(race: Race) -> str:
    distance = f", {race.distance_km:g} km" if race.distance_km else ""
    when = f", le {_fr_date(race.race_date)}" if race.race_date else ""
    return f"{race.name} ({race.city}, {race.country}{distance}{when})"


def build_task(
    kind: StepKind,
    race: Race,
    profile: RunnerProfile,
    query: str = "",
    scope: "Scope | None" = None,
) -> str:
    dates = stay_dates(race)
    stay = (
        f"arrivée le {_fr_date(dates[0])} et départ le {_fr_date(dates[1])} (2 nuits)"
        if dates
        else "pour 2 nuits : la veille et le soir de la course (vérifie d'abord la date sur le site officiel)"
    )
    notes = f" Contraintes du coureur : {scope.notes}." if scope and scope.notes else ""
    if kind is StepKind.registration:
        start = (
            f"Commence par la page d'inscription trouvée : {race.registration_url}. "
            if race.registration_url
            else "Trouve d'abord la page d'inscription officielle (site de l'organisateur "
            "ou billetterie qu'il désigne) par une recherche web. "
        )
        medical = (
            f"Justificatif médical déjà indiqué par le coureur : « {scope.medical} » ; "
            "ne le redemande pas. "
            if scope and scope.medical
            else "Si la course exige un justificatif médical, demande avec ask_user : "
            "« Avez-vous un certificat médical, une licence ou un PPS valable pour cette course ? » "
        )
        task = (
            f"Prépare l'inscription à {_race_label(race)}. {start}"
            "Passe uniquement par le site officiel de la course ou la billetterie qu'il "
            "désigne, jamais par un revendeur de dossards. "
            "Continue en invité. Utilise uniquement le profil fictif ci-dessous et "
            "remplis seulement les champs nécessaires. Si l'inscription en invité "
            "n'est pas possible, arrête-toi avant toute création de compte. "
            f"{medical}Ne coche aucune case de santé, ne fournis aucun numéro et ne "
            "téléverse aucun document ; arrête-toi à la déclaration de santé si elle "
            f"apparaît, sinon au paiement.{notes} "
            f"{_profile_lines(profile)} {ASK_USER_RULES} {STOP_RULES}"
        )
    elif kind is StepKind.accommodation:
        budget = (
            scope.budget_per_night
            if scope and scope.budget_per_night
            else extract_budget_per_night(query, require_context=True)
        )
        budget_instruction = (
            f"Budget maximal déjà donné : {budget:g} € par nuit, soit "
            f"{budget * 2:g} € maximum pour les deux nuits. Respecte strictement ce plafond."
            if budget is not None
            else "Avant toute recherche, demande avec ask_user : « Budget max par nuit ? » "
            "avec les options « 100 € », « 150 € », « 200 € ». Attends la réponse avant "
            "d'ouvrir le site."
        )
        near = race.start_location or race.bib_pickup or "du départ de la course"
        task = (
            f"Trouve un hôtel à {race.city} ({race.country}) pour 1 adulte, {stay}, "
            f"près de {near}, pour {race.name}. {budget_instruction} "
            "Utilise un site de réservation grand public (site officiel d'une chaîne "
            "hôtelière, Booking.com ou équivalent), sans créer de compte ni passer par "
            "une location entre particuliers. Compare plusieurs offres et ne choisis "
            "qu'un tarif dont le total des deux nuits respecte le plafond. "
            "Si aucune offre ne respecte le budget, ne la présente pas comme convenable "
            f"et indique qu'aucune option abordable n'a été trouvée.{notes} "
            "Arrête-toi au récapitulatif avant paiement, sans réserver. Dans la réponse "
            "finale, donne le prix total exact sous la forme "
            "PRIX_TOTAL_2_NUITS: 123.45 EUR ; si le total est absent, écris "
            "PRIX_TOTAL_2_NUITS: INCONNU. "
            f"{ASK_USER_RULES} {STOP_RULES}"
        )
    elif kind is StepKind.transport:
        origin = (
            (scope.departure_city if scope else None)
            or extract_departure_city(query)
            or profile.city
        )
        when = (
            f"aller le {_fr_date(dates[0])} et retour le {_fr_date(dates[1])}"
            if dates
            else "aller la veille de la course et retour le lendemain (vérifie la date sur le site officiel)"
        )
        timing = (
            f"Horaire de départ préféré déjà donné : {scope.travel_time} ; ne le redemande pas. "
            if scope and scope.travel_time
            else "Si plusieurs horaires ou tarifs sont possibles, demande à l'utilisateur "
            "de choisir ; ne devine pas. "
        )
        task = (
            f"Cherche un aller-retour {origin} → {race.city} ({race.country}) pour "
            f"1 adulte, pour {race.name} : {when}. Choisis le mode adapté : le train si "
            "le trajet dure moins de 7 h environ (site officiel de l'opérateur "
            "ferroviaire : SNCF Connect, Trenitalia, Renfe, Deutsche Bahn…), sinon "
            "l'avion (compare sur Google Flights, puis ouvre le site de la compagnie). "
            "Si le départ est dans la ville de la course, indique qu'aucun transport "
            f"n'est nécessaire et arrête-toi. {timing}Ne crée aucun compte.{notes} "
            f"{ASK_USER_RULES} {STOP_RULES}"
        )
    else:
        raise ValueError(f"Pas d'agent de navigation pour l'étape {kind.value}")
    return guard_task(task)
