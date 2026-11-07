"""Construction d'un `Recap` à partir des objets de mission (`runai.models`)."""

import base64
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
    utcnow,
)

from .models import FieldRow, KeyFact, Recap, RecapMission, RecapSource, TimelineItem

MISSION_TITLES: dict[StepKind, str] = {
    StepKind.registration: "Inscription à la course",
    StepKind.accommodation: "Hébergement",
    StepKind.transport: "Transport aller-retour",
}

STOP_LABELS: dict[StopPoint, str] = {
    StopPoint.payment: "page de paiement",
    StopPoint.account_creation: "création de compte",
    StopPoint.health_declaration: "certificat médical / déclaration de santé",
    StopPoint.consent: "règlement / consentement",
    StopPoint.submission: "validation définitive",
}

HUMAN_ACTIONS: dict[StopPoint, str] = {
    StopPoint.payment: "Vérifier le récapitulatif et le prix, puis payer toi-même sur le site officiel.",
    StopPoint.account_creation: "Créer toi-même ton compte : l'agent ne saisit jamais de mot de passe.",
    StopPoint.health_declaration: "Fournir toi-même le certificat médical : aucune donnée de santé ne passe par l'agent.",
    StopPoint.consent: "Lire et cocher toi-même le règlement, les CGU ou le consentement.",
    StopPoint.submission: "Relire les champs pré-remplis et valider toi-même l'envoi définitif.",
}

COUNTRY_TZ: dict[str, str] = {
    "FR": "Europe/Paris", "IT": "Europe/Rome", "ES": "Europe/Madrid", "PT": "Europe/Lisbon",
    "DE": "Europe/Berlin", "BE": "Europe/Brussels", "NL": "Europe/Amsterdam", "CH": "Europe/Zurich",
    "GB": "Europe/London", "UK": "Europe/London", "IE": "Europe/Dublin", "AT": "Europe/Vienna",
}

_MISSION_ORDER = (StepKind.registration, StepKind.accommodation, StepKind.transport)
_TIME_RE = re.compile(r"(\d{1,2})\s*[:hH]\s*(\d{2})?")


def human_action(step: StepResult) -> str:
    if step.status is StepStatus.failed:
        return "Agent bloqué : reprendre la main depuis la vue live ou relancer la mission."
    if step.status in (StepStatus.pending, StepStatus.running, StepStatus.paused):
        return "Mission pas encore terminée : attendre l'agent avant de payer quoi que ce soit."
    if step.stop_point is None:
        return "Rien n'a été engagé : vérifier la page atteinte et finaliser toi-même."
    return HUMAN_ACTIONS[step.stop_point]


def race_timezone(race: Race) -> ZoneInfo | None:
    """Fuseau du lieu de la course ; None si le pays n'est pas connu (l'heure locale reste alors en texte)."""
    name = COUNTRY_TZ.get(race.country.upper())
    return ZoneInfo(name) if name else None


def parse_start_time(value: str | None) -> time | None:
    """« 09:00 », « 9h30 », « 8 h » → time ; None si illisible."""
    m = _TIME_RE.search(value or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2) or 0))


def race_start(race: Race) -> datetime | None:
    if race.race_date is None:
        return None
    t = parse_start_time(race.start_time)
    tz = race_timezone(race)
    if t is None or tz is None:
        return None
    return datetime.combine(race.race_date, t, tzinfo=tz)


def default_timeline(race: Race) -> list[TimelineItem]:
    """Rappel du retrait du dossard (veille, jour à confirmer) et départ de la course, à l'heure locale du lieu."""
    if race.race_date is None:
        return []
    tz = race_timezone(race) or UTC
    eve = datetime.combine(race.race_date - timedelta(days=1), time(0), tzinfo=tz)
    items = [TimelineItem(
        start=eve, time_known=False, title="Retrait du dossard (jour à confirmer)",
        detail=(race.bib_pickup or "lieu et horaires à confirmer") + " · pièce d'identité et documents exigés",
        tag="info",
    )]
    start = race_start(race)
    if start is not None:
        duration = timedelta(minutes=max(60, round((race.distance_km or 10) * 6.5)))
        items.append(TimelineItem(
            start=start, end=start + duration, title=f"Départ : {race.name}",
            detail="fin estimée", location=race.start_location, tag="course", alarm_minutes=12 * 60,
        ))
    else:
        items.append(TimelineItem(
            start=datetime.combine(race.race_date, time(0), tzinfo=tz), time_known=False,
            title=f"Course : {race.name}",
            detail=(f"départ {race.start_time} (heure locale)" if race.start_time else "heure de départ à confirmer"),
            location=race.start_location, tag="course",
        ))
    return items


def default_key_facts(race: Race) -> list[KeyFact]:
    src = 1 if race.sources else None
    facts = []
    if race.race_date:
        facts.append(KeyFact(label="Départ", value=_fr_date(race.race_date) + (f" · {race.start_time}" if race.start_time else ""),
                             detail=race.start_location, source=src))
    if race.distance_km:
        facts.append(KeyFact(label="Distance", value=f"{race.distance_km:g} km".replace(".", ","), source=src))
    if race.bib_pickup:
        facts.append(KeyFact(label="Retrait du dossard", value=race.bib_pickup, source=src))
    facts.append(KeyFact(label="Lieu", value=f"{race.city} ({race.country})"))
    return facts


def _fr_date(d: date) -> str:
    days = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    return f"{days[d.weekday()]} {d.day} {months[d.month - 1]} {d.year}"


def png_data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _mission(step: StepResult, price: float | None, options: list[str], capture: bytes | None) -> RecapMission:
    fields = []
    if step.summary:
        fields.append(FieldRow(label="Ce qu'a fait l'agent", value=step.summary))
    if step.stop_point:
        fields.append(FieldRow(label="Arrêté avant", value=STOP_LABELS[step.stop_point]))
    fields += [FieldRow(label="Option", value=o) for o in options]
    if step.error:
        fields.append(FieldRow(label="Erreur", value=step.error))
    return RecapMission(
        kind=step.kind,
        title=MISSION_TITLES.get(step.kind, step.kind.value),
        status=step.status,
        stop_point=step.stop_point,
        summary=step.summary,
        fields=fields,
        price_eur=price,
        finalize_url=str(step.url) if step.url else None,
        live_view_url=str(step.live_view_url) if step.live_view_url else None,
        h_session_id=step.h_session_id,
        human_action=human_action(step),
        capture_data_uri=png_data_uri(capture) if capture else None,
        error=step.error,
    )


def recap_from_mission(
    race: Race,
    profile: RunnerProfile,
    steps: Iterable[StepResult],
    *,
    recap_id: str = "recap",
    voice_request: str | None = None,
    goal: str | None = None,
    prices: Mapping[StepKind, float] | None = None,
    options: Mapping[StepKind, list[str]] | None = None,
    timeline: list[TimelineItem] | None = None,
    extra_timeline: Iterable[TimelineItem] = (),
    key_facts: list[KeyFact] | None = None,
    checklist: Iterable[str] = (),
    extra_sources: Iterable[RecapSource] = (),
    captures: Mapping[StepKind, bytes] | None = None,
    notice: str | None = None,
    generated_at: datetime | None = None,
    calendar_timezone: str = "Europe/Paris",
) -> Recap:
    """Construit un `Recap` à partir d'une mission terminée (ou en cours).

    - `steps` : les `StepResult` de la mission ; les étapes `search` ne deviennent pas des missions,
      seule la dernière étape de chaque type (inscription, hébergement, transport) est gardée.
    - `prices` remplace `StepResult.price_eur` ; `options` ajoute des lignes « Option » à une mission.
    - `timeline` remplace la timeline par défaut (`default_timeline(race)`), `extra_timeline` la complète.
    - Sources : `race.sources` (trouvées par Linkup), `extra_sources`, puis la page où chaque agent s'est arrêté.
    - `notice` : bandeau en tête ; par défaut il rappelle que rien n'a été payé (et que le profil est fictif
      si l'e-mail est en @example.com) ; passer `""` pour le masquer.
    """
    prices, options, captures = prices or {}, options or {}, captures or {}
    last: dict[StepKind, StepResult] = {s.kind: s for s in steps if s.kind in MISSION_TITLES}
    missions = [
        _mission(last[k], prices.get(k, last[k].price_eur), list(options.get(k, [])), captures.get(k))
        for k in _MISSION_ORDER if k in last
    ]
    sources = [RecapSource(label=s.title or str(s.url), url=str(s.url), found_by="Linkup", used_for="infos de la course")
               for s in race.sources]
    sources += list(extra_sources)
    sources += [RecapSource(label=f"Page atteinte par l'agent ({m.title.lower()})", url=m.finalize_url,
                            found_by="Agent H", used_for="lien pour finaliser")
                for m in missions if m.finalize_url]
    fictive = profile.email.endswith("@example.com")
    items = list(default_timeline(race) if timeline is None else timeline) + list(extra_timeline)
    return Recap(
        id=recap_id,
        generated_at=generated_at or utcnow(),
        race_name=race.name,
        race_city=race.city,
        race_date=race.race_date,
        distance_km=race.distance_km,
        runner_name=f"{profile.first_name} {profile.last_name}",
        runner_email=profile.email,
        runner_fictive=fictive,
        goal=goal,
        voice_request=voice_request,
        notice=notice if notice is not None else (
            ("Profil coureur fictif. " if fictive else "") + "Rien n'a été payé ni soumis par RunAI."),
        key_facts=default_key_facts(race) if key_facts is None else key_facts,
        timeline=sorted(items, key=lambda t: t.start),
        missions=missions,
        checklist=list(checklist),
        sources=sources,
        calendar_timezone=calendar_timezone,
    )
