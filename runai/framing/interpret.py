"""Partial local extraction in English and French, with no default locations."""

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
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTH_NUMBERS = {
    name: number
    for names in (MONTHS, ENGLISH_MONTHS)
    for number, name in enumerate(names, 1)
}
MONTH_PATTERN = "|".join(MONTH_NUMBERS)
SEASONS = {
    "spring": (3, 5, ENGLISH_MONTHS),
    "summer": (6, 8, ENGLISH_MONTHS),
    "autumn": (9, 11, ENGLISH_MONTHS),
    "fall": (9, 11, ENGLISH_MONTHS),
    "winter": (12, 2, ENGLISH_MONTHS),
    "printemps": (3, 5, MONTHS),
    "été": (6, 8, MONTHS),
    "ete": (6, 8, MONTHS),
    "automne": (9, 11, MONTHS),
    "hiver": (12, 2, MONTHS),
}
TEMPORAL_PATTERN = MONTH_PATTERN + "|" + "|".join(SEASONS)
LOCATION_BOUNDARY = (
    r"(?=\s+(?:depuis|from|leaving|departing|au départ|en|in|le|pour|avec|with|budget|au|on|by|"
    r"flying|édition|edition|next|prochain|prochaine|"
    + MONTH_PATTERN
    + r"|\d+)\b|[,;.!?]|$)"
)
HINT_BOUNDARY = (
    r"(?=\s*(?:[,;.!?]|$)|\s+(?:from|depuis|en|in|à|au|on|for|pour|"
    r"avec|with|édition|edition|by|budget)\b)"
)


def _is_temporal(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"next|prochain|prochaine|(?:(?:next|prochain|prochaine)\s+)?(?:"
            + TEMPORAL_PATTERN
            + r")",
            value,
            re.IGNORECASE,
        )
    )


def _is_negated(text: str, start: int) -> bool:
    return bool(
        re.search(
            r"\b(?:not|pas|sans|no)\b(?:\s+(?:a|an|the|de|un|une|du|le|la))?\s*$",
            text[:start],
            re.IGNORECASE,
        )
    )


def _extract_dates(text: str, current: date) -> dict[SlotName, object]:
    result: dict[SlotName, object] = {}
    edition = re.search(r"\b(?:édition|edition)\s+(\d{4})\b", text, re.IGNORECASE)
    if not edition:
        edition = re.search(r"\b(?:en|in)\s+(\d{4})\b", text, re.IGNORECASE)
    if edition:
        result[SlotName.edition] = edition[1]
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    day_first = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th|er)?\s+(" + MONTH_PATTERN + r")\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    month_first = re.search(
        r"\b(" + MONTH_PATTERN + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*|\s+)(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    try:
        if iso:
            result[SlotName.race_date] = date.fromisoformat(iso[0]).isoformat()
        elif day_first or month_first:
            match = day_first or month_first
            day, month = (match[1], match[2]) if day_first else (match[2], match[1])
            result[SlotName.race_date] = date(
                int(match[3]), MONTH_NUMBERS[month.lower()], int(day)
            ).isoformat()
        else:
            month = re.search(
                r"\b(?:(next)\s+)?("
                + MONTH_PATTERN
                + r")(?:\s+(\d{4})\b|"
                + HINT_BOUNDARY
                + r")",
                text,
                re.IGNORECASE,
            )
            if month:
                name = month[2].lower()
                number = MONTH_NUMBERS[name]
                year = int(month[3] or (edition[1] if edition else 0)) or (
                    current.year
                    + (
                        number < current.month
                        or (bool(month[1]) and number == current.month)
                    )
                )
                result[SlotName.date_window] = f"{name} {year}"
            # Let the engine preserve this standalone legacy reply as free text.
            elif not re.fullmatch(r"\s*au printemps\s*[.!?]?\s*", text, re.IGNORECASE):
                season = re.search(
                    r"\b("
                    + "|".join(SEASONS)
                    + r")(?:\s+(\d{4})\b|"
                    + HINT_BOUNDARY
                    + r")",
                    text,
                    re.IGNORECASE,
                )
                if season:
                    start, end, names = SEASONS[season[1].lower()]
                    year = int(season[2] or (edition[1] if edition else 0)) or (
                        current.year
                        + (end < current.month if start <= end else 0)
                        - (start > end and current.month <= end)
                    )
                    first, last = names[start - 1], names[end - 1]
                    result[SlotName.date_window] = (
                        f"{first}-{last} {year}"
                        if start <= end
                        else f"{first} {year}-{last} {year + 1}"
                    )
        english_year = re.search(
            r"\b(?:" + "|".join(ENGLISH_MONTHS) + "|spring|summer|autumn|fall|winter)"
            r"\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(\d{4})\b",
            text, re.IGNORECASE,
        )
        if not edition and english_year:
            result[SlotName.edition] = english_year[1]
        standalone_season = re.fullmatch(
            r"\s*(spring|summer|autumn|fall|winter)(?:\s+\d{4})?\s*", text, re.IGNORECASE
        )
        if standalone_season:
            result[SlotName.date_window] = text.strip().lower()
    except ValueError:
        pass
    return result


def english_race(text: str) -> re.Match | None:
    return re.search(
        r"\b(?!(?i:un|une|le|la|les|a|an|the|my|half|semi|ultra)\b)"
        r"([A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*){0,2})"
        r"\s+(?i:half(?:[ -]marathon)?|marathon|(?:10|5|21)\s*k(?:m)?|trail)\b",
        text,
    )


def extract_slots(text: str, today: date | None = None) -> dict[SlotName, object]:
    result: dict[SlotName, object] = {}
    boundary = LOCATION_BOUNDARY
    english = english_race(text)
    if english and not any(_is_temporal(word) for word in english[1].split()):
        result[SlotName.city] = english[1]
        result[SlotName.race] = english[0]
    for slot, prefix in (
        (SlotName.origin, r"(?:depuis|au départ de|départ de|leaving\s+from|departing(?:\s+from)?|from)"),
        (SlotName.city, r"(?:à|in|(?:marathon|semi|course|race)\s+(?:de|of))"),
    ):
        matches = re.finditer(
            r"\b" + prefix + r"\s+([^\W\d_][\wÀ-ž '’\-]*?)" + boundary,
            text,
            re.IGNORECASE,
        )
        for match in matches:
            value = match[1].strip()
            if slot not in result and not _is_temporal(value) and not re.search(
                r"\b(?:ou|or)\b", value, re.IGNORECASE
            ):
                result[slot] = value
                break
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
                r"(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*" + boundary,
                text,
            )
        if named_race:
            result[SlotName.race] = named_race[0].strip(" ,;.!?")
    if SlotName.city not in result and SlotName.race not in result:
        excluded = (
            r"i|want|would|like|to|run|running|the|a|an|half|semi|marathon|race|"
            r"not|no|pas|sans|de|of|un|une|in|à|from|depuis|and|or|ou|"
            + TEMPORAL_PATTERN
        )
        word = r"(?!(?:" + excluded + r")\b)[^\W\d_][\w'’\-]*"
        before_race = re.search(
            r"\b(" + word + r"(?:\s+" + word + r")*)\s+"
            r"(?:marathon|\d+(?:[.,]\d+)?\s*k(?:m)?)\b",
            text,
            re.IGNORECASE,
        )
        if before_race and not _is_negated(text, before_race.start()):
            result[SlotName.city] = before_race[1]
    for distance in re.finditer(
        r"\b(\d+(?:[.,]\d+)?)\s*(km|k|miles?)\b", text, re.IGNORECASE
    ):
        if not _is_negated(text, distance.start()):
            km = float(distance[1].replace(",", "."))
            result[SlotName.distance_km] = (
                round(km * 1.609344, 6)
                if distance[2].lower().startswith("mile")
                else 21.0975 if km == 21 and distance[2].lower() == "k" else km
            )
            break
    if SlotName.distance_km not in result:
        for distance in re.finditer(
            r"\b(?:semi(?:[ -]marathon)?|half(?:[ -]marathon)?|marathon)\b",
            text,
            re.IGNORECASE,
        ):
            if not _is_negated(text, distance.start()):
                result[SlotName.distance_km] = (
                    42.195 if distance[0].lower() == "marathon" else 21.0975
                )
                break
    result.update(_extract_dates(text, today or date.today()))
    currency = r"(?:€|£|\$|euros?\b|eur\b|pounds?\b|dollars?\b)"
    amount = r"(\d+(?:[.,]\d+)?)"
    budget = re.search(
        r"\b" + amount + r"\s*" + currency + "|" + currency + r"\s*" + amount,
        text,
        re.IGNORECASE,
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
        (r"avion|flight|plane|flying", "flight"),
        (r"voiture|by car|rental car|drive", "car"),
        (r"bus", "bus"),
    ):
        if re.search(r"\b(?:" + pattern + r")\b", text, re.IGNORECASE):
            result[SlotName.transport_mode] = mode
    return result
