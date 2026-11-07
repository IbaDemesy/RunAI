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
ENGLISH_MONTHS = [
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
]
MONTH_NUMBERS = {name: index + 1 for names in (MONTHS, ENGLISH_MONTHS)
                 for index, name in enumerate(names)}
SEASONS = r"spring|summer|autumn|fall|winter"


def english_race(text: str) -> re.Match | None:
    return re.search(
        r"\b(?!(?i:un|une|le|la|les|a|an|the|my|half|semi|ultra)\b)"
        r"([A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*){0,2})"
        r"\s+(?i:half(?:[ -]marathon)?|marathon|(?:10|5|21)\s*k(?:m)?|trail)\b",
        text,
    )


def extract_slots(text: str, today: date | None = None) -> dict[SlotName, object]:
    result: dict[SlotName, object] = {}
    boundary = r"(?=\s+(?:depuis|from|leaving|departing|au départ|en|in|le|pour|avec|with|budget|au|on|édition|edition|\d+)\b|[,;.!?]|$)"
    english = english_race(text)
    if english and not any(word.lower() in MONTH_NUMBERS or re.fullmatch(SEASONS, word.lower())
                           for word in english[1].split()):
        result[SlotName.city] = english[1]
        result[SlotName.race] = english[0]
    for slot, prefix in (
        (SlotName.origin, r"(?:depuis|au départ de|départ de|leaving\s+from|departing(?:\s+from)?|from)"),
        (SlotName.city, r"(?:à|in|(?:marathon|semi|course|race) de)"),
    ):
        match = re.search(
            r"\b" + prefix + r"\s+([^\W\d_][\wÀ-ž '\-]*?)" + boundary,
            text,
            re.IGNORECASE,
        )
        if (match and slot not in result
                and not any(word.lower() in MONTH_NUMBERS or re.fullmatch(SEASONS, word.lower())
                            for word in match[1].split())
                and not re.search(r"\b(?:ou|or)\b", match[1], re.IGNORECASE)):
            result[slot] = match[1].strip()
    named_race = re.search(
        r"\b(?i:ultra-trail|trail|ultra|course|corrida|foulées|ekiden|raid)"
        r"\s+(?i:des|du|de la|de l['’]|d['’])\s*"
        r"[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*"
        r"(?=\s+(?i:à|a|depuis|from|au départ|en|in|le|pour|avec|budget|au|on|"
        r"édition|edition|\d+)\b|[,;.!?]|$)",
        text,
    )
    if named_race:
        result[SlotName.race] = named_race[0].strip(" ,;.!?")
    else:
        named_race = re.search(
            r"\bMarathon\s+de\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*"
            + boundary,
            text,
        )
        if not named_race:
            named_race = re.search(
                r"\b(?!(?i:trail|run|marathon|semi)(?:-marathon)?\b)"
                r"[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*?(?i:trail|run|marathon)[\wÀ-ž'’\-]*"
                r"(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*"
                + boundary,
                text,
            )
        if named_race:
            result[SlotName.race] = named_race[0].strip(" ,;.!?")
    distance = re.search(r"\b(\d+(?:[.,]\d+)?)\s*k(?:m)?\b", text, re.IGNORECASE)
    if distance:
        value = float(distance[1].replace(",", "."))
        result[SlotName.distance_km] = 21.0975 if value == 21 and distance[0].lower().endswith("k") else value
    elif not re.search(r"pas|not|sans", text, re.IGNORECASE) and re.search(
        r"\bsemi(?:-marathon)?\b|\bhalf(?:[ -]marathon)?\b", text, re.IGNORECASE
    ):
        result[SlotName.distance_km] = 21.0975
    elif not re.search(r"pas|not|sans", text, re.IGNORECASE) and re.search(
        r"\bmarathon\b", text, re.IGNORECASE
    ):
        result[SlotName.distance_km] = 42.195
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    french = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(MONTH_NUMBERS) + r")\s+(\d{4})\b", text, re.IGNORECASE
    )
    american = re.search(
        r"\b(" + "|".join(ENGLISH_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b",
        text, re.IGNORECASE,
    )
    edition = re.search(r"\b(?:édition|edition)\s+(\d{4})\b", text, re.IGNORECASE)
    if not edition:
        edition = re.search(r"\b(?:en|in)\s+(\d{4})\b", text, re.IGNORECASE)
    try:
        if iso:
            result[SlotName.race_date] = date.fromisoformat(iso[0]).isoformat()
        elif french:
            result[SlotName.race_date] = date(
                int(french[3]), MONTH_NUMBERS[french[2].lower()], int(french[1])
            ).isoformat()
        elif american:
            result[SlotName.race_date] = date(
                int(american[3]), MONTH_NUMBERS[american[1].lower()], int(american[2])
            ).isoformat()
        else:
            window = re.search(
                r"\b(?:" + "|".join(MONTH_NUMBERS) + r")\s+\d{4}\b", text, re.IGNORECASE
            )
            if window:
                result[SlotName.date_window] = window[0].lower()
            else:
                month_only = re.search(
                    r"\b(?:(?:en|in)\s+(?:mois\s+de\s+)?|au\s+mois\s+de\s+)("
                    + "|".join(MONTH_NUMBERS)
                    + r")\b",
                    text,
                    re.IGNORECASE,
                )
                if month_only:
                    current = today or date.today()
                    month = MONTH_NUMBERS[month_only[1].lower()]
                    year = (
                        int(edition[1])
                        if edition
                        else current.year + (month < current.month)
                    )
                    result[SlotName.date_window] = f"{month_only[1].lower()} {year}"
    except ValueError:
        pass
    season = re.search(r"\b(" + SEASONS + r")(?:\s+(\d{4}))?\b", text, re.IGNORECASE)
    if season and SlotName.race_date not in result and SlotName.date_window not in result:
        result[SlotName.date_window] = season[0].lower()
    english_year = re.search(
        r"\b(?:" + "|".join(ENGLISH_MONTHS) + "|" + SEASONS + r")\s+(?:\d{1,2},?\s+)?(\d{4})\b",
        text, re.IGNORECASE,
    )
    if not edition:
        edition = english_year
    if edition:
        result[SlotName.edition] = edition[1]
    budget = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(?:€|£|\$|euros?\b|pounds?\b|dollars?\b)"
        r"|[£$€]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE,
    )
    if budget:
        result[SlotName.budget] = float((budget[1] or budget[2]).replace(",", "."))
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
