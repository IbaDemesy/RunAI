import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from runai.search.models import Issue, IssueLevel, RaceSheet

KNOWN_REGISTRATION_PLATFORMS = (
    "njuko.net",
    "njuko.com",
    "klikego.com",
    "timeto.com",
    "endu.net",
    "maratonaportugal.com",
    "runsignup.com",
    "active.com",
)

AGGREGATOR_DOMAINS = (
    "ahotu.com",
    "worldsmarathons.com",
    "findarace.com",
    "racecheck.com",
    "13milers.com",
    "beforerace.day",
    "runningintheusa.com",
    "marathonrunnersdiary.com",
    "wikipedia.org",
)

REQUIRED_FIELDS = (
    "name",
    "city",
    "country",
    "race_date",
    "start_time",
    "distance_km",
    "registration_url",
    "start_location",
    "bib_pickup.location",
    "bib_pickup.days",
    "bib_pickup.hours",
)

HALF_MARATHON_KM = 21.0975
MARATHON_KM = 42.195
MAX_PICKUP_DAYS_BEFORE_RACE = 10

_SECOND_LEVEL_SUFFIXES = frozenset(
    {"co", "com", "org", "net", "gov", "gouv", "edu", "ac", "or", "ne", "go", "asso", "nom"}
)

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_YEAR = re.compile(r"\b(20\d{2})\b")
_HALF = re.compile(r"\b(semi|half|meia|mezza|media)\b", re.IGNORECASE)
_MARATHON = re.compile(r"marat(h)?on", re.IGNORECASE)
_KM = re.compile(r"\b(\d{1,3})\s?(k|km)\b", re.IGNORECASE)


def host_of(url: object) -> str:
    return (urlsplit(str(url)).hostname or "").lower().removeprefix("www.")


def base_domain(host: str) -> str:
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def expected_distance_km(query: str) -> float | None:
    if _HALF.search(query):
        return HALF_MARATHON_KM
    if _MARATHON.search(query):
        return MARATHON_KM
    if match := _KM.search(query):
        return float(match.group(1))
    return None


def is_aggregator(host: str) -> bool:
    return any(on_domain(host, domain) for domain in AGGREGATOR_DOMAINS)


def registration_url_issue(sheet: RaceSheet) -> Issue | None:
    if sheet.registration_url is None:
        return None
    host = host_of(sheet.registration_url)
    if is_aggregator(host):
        return Issue(
            field="registration_url",
            level=IssueLevel.error,
            message=f"{host} est un agrégateur, pas le site officiel ni une plateforme d'inscription",
        )
    if sheet.registration_verified or any(on_domain(host, domain) for domain in KNOWN_REGISTRATION_PLATFORMS):
        return None
    if sheet.official_url is not None and on_domain(host, base_domain(host_of(sheet.official_url))):
        return None
    return Issue(
        field="registration_url",
        level=IssueLevel.error,
        message=f"{host} n'est ni le domaine officiel de la course ni une plateforme d'inscription connue",
    )


def missing_fields(sheet: RaceSheet) -> list[str]:
    missing = []
    for field in REQUIRED_FIELDS:
        value = sheet
        for part in field.split("."):
            value = getattr(value, part)
        if value in (None, "", []):
            missing.append(field)
    return missing


def check_sheet(sheet: RaceSheet, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    if sheet.race_date is not None:
        if sheet.race_date <= today:
            issues.append(
                Issue(
                    field="race_date",
                    level=IssueLevel.error,
                    message=f"la date {sheet.race_date.isoformat()} n'est pas dans le futur",
                )
            )
        years = {int(year) for year in _YEAR.findall(sheet.query)}
        if years and sheet.race_date.year not in years:
            issues.append(
                Issue(
                    field="race_date",
                    level=IssueLevel.error,
                    message=f"édition {sheet.race_date.year} trouvée, {sorted(years)} demandée",
                )
            )

    if sheet.start_time is not None and not _TIME.match(sheet.start_time):
        issues.append(
            Issue(field="start_time", level=IssueLevel.warning, message=f"heure non reconnue : {sheet.start_time!r}")
        )

    expected = expected_distance_km(sheet.query)
    if sheet.distance_km is not None:
        if sheet.distance_km <= 0:
            issues.append(Issue(field="distance_km", level=IssueLevel.error, message="distance nulle ou négative"))
        elif expected is not None and abs(sheet.distance_km - expected) > 0.5:
            issues.append(
                Issue(
                    field="distance_km",
                    level=IssueLevel.error,
                    message=f"{sheet.distance_km} km trouvés, environ {expected} km attendus pour la demande",
                )
            )

    if issue := registration_url_issue(sheet):
        issues.append(issue)

    if sheet.race_date is not None:
        earliest = sheet.race_date - timedelta(days=MAX_PICKUP_DAYS_BEFORE_RACE)
        for day in sheet.bib_pickup.days:
            if not earliest <= day <= sheet.race_date:
                issues.append(
                    Issue(
                        field="bib_pickup.days",
                        level=IssueLevel.warning,
                        message=f"retrait le {day.isoformat()}, incohérent avec une course le {sheet.race_date.isoformat()}",
                    )
                )

    if not sheet.sources:
        issues.append(Issue(field="sources", level=IssueLevel.error, message="aucune source renvoyée"))

    for field in missing_fields(sheet):
        issues.append(Issue(field=field, level=IssueLevel.warning, message="information introuvable dans les sources"))

    return issues
