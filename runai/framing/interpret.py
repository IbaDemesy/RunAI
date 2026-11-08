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
MONTH_NUMBERS.update({month[:3]: i for i, month in enumerate(ENGLISH_MONTHS, 1)})
MONTH_NUMBERS["sept"] = 9
MONTH_PATTERN = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
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
DATE_WORDS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "this"}
NIGHT_NUMBERS = dict(zip(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), range(1, 11)))
NIGHT_NUMBERS |= {"un": 1, "une": 1} | dict(zip(("deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix"), range(2, 11)))
WORD_AMOUNTS = {"cent": 100, "cents": 100, "hundred": 100, "mille": 1000, "thousand": 1000} | NIGHT_NUMBERS
LOCATION_BOUNDARY = (
    r"(?=\s+(?:depuis|from|to|this|leaving|departing|au départ|en|in|le|pour|avec|with|budget|au|on|by|"
    r"flying|édition|edition|next|prochain|prochaine|for|and|et|because|so|but|while|where|"
    + MONTH_PATTERN
    + r"|\d+)\b|[,;.!?]|$)"
)
HINT_BOUNDARY = (
    r"(?=\s*(?:[,;.!?]|$)|\s+(?:from|depuis|en|in|à|au|on|for|pour|"
    r"avec|with|édition|edition|by|budget)\b)"
)


def normalize_date_window(value: str) -> str:
    match = re.fullmatch(rf"({MONTH_PATTERN})\.?\s+(\d{{4}})", value.strip(), re.IGNORECASE)
    if not match:
        return value
    return f"{ENGLISH_MONTHS[MONTH_NUMBERS[match[1].lower()] - 1].title()} {match[2]}"


def _is_temporal(value: str) -> bool:
    if value.casefold() in DATE_WORDS:
        return True
    return bool(
        re.fullmatch(
            r"next|prochain|prochaine|(?:(?:next|prochain|prochaine)\s+)?(?:"
            + TEMPORAL_PATTERN
            + r")",
            value,
            re.IGNORECASE,
        )
    )


CITY_STOPWORDS = {
    "i", "my", "me", "the", "a", "an", "je", "j", "le", "la", "les", "un", "une", "mon", "ma", "mes",
    "want", "veux", "cours", "run", "need", "live", "vis", "habite", "first", "premier", "première",
}


def _plausible_city(value: str) -> bool:
    words = re.findall(r"[\wÀ-ž'’\-]+", value)
    return 0 < len(words) <= 3 and not any(
        word.casefold() in CITY_STOPWORDS and word not in {"Le", "La", "Les"} for word in words
    )


def _parse_amount(raw: str) -> float:
    value = raw.strip().lower()
    factor = 1000.0 if value.endswith("k") else 1.0
    value = value.rstrip("k").strip()
    grouped = re.fullmatch(r"(\d{1,3}(?:[ ,.\u00a0\u202f]\d{3})+)(?:[.,](\d{1,2}))?", value)
    if grouped:
        return float(re.sub(r"\D", "", grouped[1]) + "." + (grouped[2] or "0")) * factor
    return float(value.replace(",", ".")) * factor


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
        words = english[1].split()
        while words and words[0].casefold() in {"run", "do", "book", "register", "join", "find", "i", "want", "please", "to", "would", "like", "need", "let", "me"}:
            words.pop(0)
        if words:
            result[SlotName.city] = " ".join(words)
            result[SlotName.race] = " ".join(words) + english[0][len(english[1]):]
    for slot, prefix in (
        (SlotName.origin, r"(?:depuis|au départ de|départ de|leaving\s+from|departing(?:\s+from)?|from)"),
        (SlotName.city, r"(?<!live )(?<!vis )(?<!habite )(?:à|in|(?:marathon|semi|course|race|\d+\s*km?)\s+(?:de|of))"),
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
            ) and (slot != SlotName.city or _plausible_city(value)):
                result[slot] = value
                break
    if SlotName.city not in result:
        destination = re.search(
            r"\b(?i:to)\s+([A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*)" + boundary,
            text,
        )
        after_distance = re.search(
            r"\b(?i:10\s*k(?:m)?|ten\s+k|half(?:\s+marathon)?|HM)\s+"
            r"([A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž'’\-]*)*)" + boundary,
            text,
        )
        for match in (destination, after_distance):
            if match and not _is_temporal(match[1]) and match[1].casefold() not in {"run", "race"} and _plausible_city(match[1]):
                result[SlotName.city] = match[1]
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
        if before_race and before_race[1][0].isupper() and not _is_temporal(before_race[1]) and not _is_negated(text, before_race.start()) and _plausible_city(before_race[1]):
            result[SlotName.city] = before_race[1]
    for distance in re.finditer(
        r"\b(\d+(?:[.,]\d+)?)\s*(km|k|miles?)\b", text, re.IGNORECASE
    ):
        if distance[2].lower() == "k" and re.match(
            r"\s*(?:€|£|\$|euros?\b|eur\b|pounds?\b|dollars?\b)", text[distance.end():], re.IGNORECASE
        ):
            continue
        if not _is_negated(text, distance.start()):
            km = float(distance[1].replace(",", "."))
            result[SlotName.distance_km] = (
                round(km * 1.609344, 6)
                if distance[2].lower().startswith("mile")
                else 21.0975 if km == 21 and distance[2].lower() == "k" else km
            )
            break
    if SlotName.distance_km not in result:
        if re.search(r"\bten\s+k\b", text, re.IGNORECASE):
            result[SlotName.distance_km] = 10.0
        for distance in re.finditer(
            r"\b(?:semi(?:[ -]marathon)?|half(?:[ -]marathon)?|HM|marathon)\b",
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
    amount = r"(\d{1,3}(?:[ ,.\u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?(?![.,]?\d)|\d+(?:[.,]\d+)?\s*k\b|\d+(?:[.,]\d+)?)"
    budget = re.search(
        r"\b" + amount + r"\s*" + currency + "|" + currency + r"\s*" + amount
        + r"|\bbudget\s+(?:is\s+|of\s+|de\s+|:\s*)?(?:around\s+|about\s+|environ\s+)?" + amount,
        text,
        re.IGNORECASE,
    )
    if budget:
        result[SlotName.budget] = _parse_amount(budget[1] or budget[2] or budget[3])
    elif re.search(r"pas de budget|sans plafond|no budget", text, re.IGNORECASE):
        result[SlotName.budget] = None
    if SlotName.budget not in result:
        words = re.search(
            r"\b((?:(?:" + "|".join(WORD_AMOUNTS) + r")[\s-]*)+)" + currency, text, re.IGNORECASE
        )
        if words:
            total = current = 0
            for word in re.findall(r"[a-zé]+", words[1].lower()):
                factor = WORD_AMOUNTS[word]
                if factor >= 1000:
                    total, current = total + (current or 1) * factor, 0
                elif factor == 100:
                    current = (current or 1) * factor
                else:
                    current += factor
            result[SlotName.budget] = float(total + current)
        elif re.search(r"\bno limit\b|pas de limite|sans limite", text, re.IGNORECASE):
            result[SlotName.budget] = None
    nights = re.search(r"\b(\d+|" + "|".join(NIGHT_NUMBERS) + r")\s*(?:nuits?|nights?)\b", text, re.IGNORECASE)
    if nights and (not nights[1].isdigit() or int(nights[1]) <= 30):
        result[SlotName.nights] = int(nights[1]) if nights[1].isdigit() else NIGHT_NUMBERS[nights[1].lower()]
    elif re.search(r"\b(?:un|a|one)\s+week-?\s?end\b", text, re.IGNORECASE):
        result[SlotName.nights] = 2
    elif re.search(r"\b(?:une|a|one)\s+(?:semaine|week)\b", text, re.IGNORECASE):
        result[SlotName.nights] = 7
    modes = []
    for pattern, mode in (
        (r"train|tgv|eurostar|sncf|rer", "train"),
        (r"avion|vol|flight|plane|flying|ryanair|easyjet", "flight"),
        (r"voiture|covoiturage|blablacar|by car|rental car|drive", "car"),
        (r"bus|flixbus", "bus"),
    ):
        for match in re.finditer(r"\b(?:" + pattern + r")\b", text, re.IGNORECASE):
            prefix = text[:match.start()]
            negated = _is_negated(text, match.start()) or re.search(
                r"\b(?:not|pas)\s+(?:by|en|in|the|a|par)\s*(?:the\s+)?$", prefix, re.IGNORECASE
            )
            modes.append((match.start(), mode, bool(negated)))
    chosen = next((mode for _, mode, negated in sorted(modes) if not negated), None)
    if chosen:
        result[SlotName.transport_mode] = chosen
    if text.strip().lower() == "car":
        result[SlotName.transport_mode] = "car"
    return result
