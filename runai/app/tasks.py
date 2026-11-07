"""Consignes envoyées aux agents et actions laissées à l'humain au portail."""

import re

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


def build_task(
    kind: StepKind,
    race: Race,
    profile: RunnerProfile,
    query: str = "",
) -> str:
    if kind is StepKind.registration:
        url = race.registration_url or "le lien Njuko de la fiche Linkup"
        distance = f" ({race.distance_km:g} km)" if race.distance_km else " (42,195 km)"
        task = (
            f"Prépare l'inscription au Wizz Air Milano Marathon 2027 sur Njuko, "
            f"à partir du lien Njuko fourni par Linkup : {url}{distance}. "
            "N'utilise jamais Klikego ; si le lien fourni n'est pas sur Njuko, arrête-toi "
            "et signale que le lien Njuko manque. "
            "Continue en invité. Utilise uniquement le profil fictif ci-dessous et "
            "remplis seulement les champs nécessaires. Si l'inscription en invité "
            "n'est pas possible, arrête-toi avant toute création de compte. "
            "Avant de poursuivre, demande exactement avec ask_user : « Avez-vous une "
            "Runcard ou un certificat médical de compétition (ECG d'effort) ? » "
            "Ne coche aucune "
            "case de santé, ne fournis aucun numéro et ne téléverse aucun document ; "
            "arrête-toi à la déclaration de santé si elle apparaît, sinon au paiement. "
            f"{_profile_lines(profile)} {ASK_USER_RULES} {STOP_RULES}"
        )
    elif kind is StepKind.accommodation:
        budget = extract_budget_per_night(query, require_context=True)
        budget_instruction = (
            f"Budget maximal déjà donné : {budget:g} € par nuit, soit "
            f"{budget * 2:g} € maximum pour les deux nuits. Respecte strictement ce plafond."
            if budget is not None
            else "Avant toute recherche, demande avec ask_user : « Budget max par nuit ? » "
            "avec les options « 100 € », « 150 € », « 200 € ». Attends la réponse avant "
            "d'ouvrir le site."
        )
        task = (
            "Trouve un hôtel à Milan pour 1 adulte, arrivée le 3 avril 2027 et départ "
            "le 5 avril 2027 (2 nuits), près du départ Corso Sempione ou du retrait "
            "des dossards Via Moncucco 35. "
            f"{budget_instruction} Va exclusivement sur le site officiel Accor "
            "(https://all.accor.com) ; Booking.com, Expedia, Hotels.com, Airbnb et tout "
            "autre agrégateur sont interdits. Compare les offres Accor disponibles et "
            "ne choisis qu'un tarif dont le total des deux nuits respecte le plafond. "
            "Si aucune offre ne respecte le budget, ne la présente pas comme convenable "
            "et indique qu'aucune option abordable n'a été trouvée. "
            "Arrête-toi au récapitulatif avant paiement, sans réserver. Dans la réponse "
            "finale, donne le prix total exact sous la forme "
            "PRIX_TOTAL_2_NUITS: 123.45 EUR ; si le total est absent, écris "
            "PRIX_TOTAL_2_NUITS: INCONNU. "
            f"{ASK_USER_RULES} {STOP_RULES}"
        )
    elif kind is StepKind.transport:
        task = (
            "Cherche un aller-retour en train Paris → Milano sur trenitalia.com pour "
            "1 adulte : aller le 3 avril 2027 et retour le 5 avril 2027. N'utilise "
            "aucun autre vendeur et jamais TAP. Si plusieurs horaires ou tarifs sont "
            "possibles, demande à l'utilisateur de choisir ; ne devine pas. "
            f"{ASK_USER_RULES} {STOP_RULES}"
        )
    else:
        raise ValueError(f"Pas d'agent de navigation pour l'étape {kind.value}")
    return guard_task(task)
