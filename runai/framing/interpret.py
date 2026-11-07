"""Extraction locale et partielle : aucune ville ni origine par défaut."""

import re
from datetime import date

from runai.contracts.framing import SlotName

MONTHS = [
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
]


def extract_slots(text: str) -> dict[SlotName, object]:
    result: dict[SlotName, object] = {}
    boundary = r"(?=\s+(?:depuis|from|au départ|en|in|le|pour|avec|budget|au|on|\d)\b|[,;.!?]|$)"
    for slot, prefix in (
        (SlotName.origin, r"(?:depuis|au départ de|départ de|from)"),
        (SlotName.city, r"(?:à|in|(?:marathon|semi|course|race) de)"),
    ):
        match = re.search(
            r"\b" + prefix + r"\s+([\wÀ-ž][\wÀ-ž '\-]*?)" + boundary,
            text,
            re.IGNORECASE,
        )
        if match and not re.search(r"\b(?:ou|or)\b", match[1], re.IGNORECASE):
            result[slot] = match[1].strip()
    distance = re.search(r"\b(\d+(?:[.,]\d+)?)\s*km\b", text, re.IGNORECASE)
    if distance:
        result[SlotName.distance_km] = float(distance[1].replace(",", "."))
    elif not re.search(r"pas|not|sans", text, re.IGNORECASE) and re.search(
        r"\bsemi(?:-marathon)?\b|\bhalf marathon\b", text, re.IGNORECASE
    ):
        result[SlotName.distance_km] = 21.0975
    elif not re.search(r"pas|not|sans", text, re.IGNORECASE) and re.search(
        r"\bmarathon\b", text, re.IGNORECASE
    ):
        result[SlotName.distance_km] = 42.195
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    french = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text, re.IGNORECASE
    )
    try:
        if iso:
            result[SlotName.race_date] = date.fromisoformat(iso[0]).isoformat()
        elif french:
            result[SlotName.race_date] = date(
                int(french[3]), MONTHS.index(french[2].lower()) + 1, int(french[1])
            ).isoformat()
        else:
            window = re.search(
                r"\b(?:" + "|".join(MONTHS) + r")\s+\d{4}\b", text, re.IGNORECASE
            )
            if window:
                result[SlotName.date_window] = window[0]
    except ValueError:
        pass
    edition = re.search(r"\b(?:édition|edition)\s+(\d{4})\b", text, re.IGNORECASE)
    if edition:
        result[SlotName.edition] = edition[1]
    budget = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:€|euros?\b)", text, re.IGNORECASE)
    if budget:
        result[SlotName.budget] = float(budget[1].replace(",", "."))
    elif re.search(r"pas de budget|sans plafond|no budget", text, re.IGNORECASE):
        result[SlotName.budget] = None
    nights = re.search(r"\b(\d+)\s*(?:nuits?|nights?)\b", text, re.IGNORECASE)
    if nights:
        result[SlotName.nights] = int(nights[1])
    for pattern, mode in (
        (r"train", "train"),
        (r"avion|flight|plane", "flight"),
        (r"voiture|by car|rental car|drive", "car"),
        (r"bus", "bus"),
    ):
        if re.search(r"\b(?:" + pattern + r")\b", text, re.IGNORECASE):
            result[SlotName.transport_mode] = mode
    return result
