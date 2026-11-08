"""Lancement : un `FramingSession` confirmé devient une `Race` + consignes par étape.

Ville, dates, nuits, distance, origine, budget et transport viennent uniquement du résumé
confirmé, des slots connus et du `RaceCandidate` sourcé choisi. Un poste non couvert par une
plateforme autorisée devient une `Limitation` (lien officiel manuel), jamais un faux résultat.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from runai.app.providers import (
    StepCoverage,
    accommodation_coverage,
    normalize_transport_mode,
    registration_coverage,
    transport_coverage,
)
from runai.app.tasks import TripBrief, build_task
from runai.contracts.common import Automation, DataMode, Limitation
from runai.contracts.framing import (
    FramingError,
    FramingSession,
    FramingStatus,
    RaceCandidate,
    SlotName,
    missing_slots,
)
from runai.journey import public_origin
from runai.models import Race, RunnerProfile, StepKind

AGENT_STEPS = (StepKind.registration, StepKind.accommodation, StepKind.transport)


class StepPlan(BaseModel):
    kind: StepKind
    automation: Automation
    platform: str | None = None
    start_url: str | None = None
    start_url_kind: str | None = None
    task: str | None = None
    limitations: list[Limitation] = Field(default_factory=list)


class LaunchPlan(BaseModel):
    framing_id: str
    revision: int
    mode: DataMode
    race: Race
    brief: TripBrief
    steps: dict[StepKind, StepPlan]
    limitations: list[Limitation] = Field(default_factory=list)

    def automated_steps(self) -> list[StepKind]:
        return [
            k
            for k, step in self.steps.items()
            if step.automation is Automation.automated
        ]


def _slot_value(session: FramingSession, name: SlotName) -> Any:
    slot = session.slots.get(name)
    return slot.value if slot is not None and slot.is_known else None


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _selected_candidate(session: FramingSession) -> RaceCandidate | None:
    if session.selected_candidate_id is None:
        return None
    for candidate in session.candidates:
        if candidate.id == session.selected_candidate_id:
            return candidate
    raise FramingError(f"Candidat choisi introuvable : {session.selected_candidate_id}")


def _check_confirmed(session: FramingSession) -> None:
    if session.status not in (FramingStatus.confirmed, FramingStatus.launched):
        raise FramingError(f"Cadrage non confirmé : {session.status.value}")
    if session.confirmed_revision != session.revision:
        raise FramingError(
            f"Confirmation de la révision {session.confirmed_revision}, courante {session.revision}"
        )
    if session.summary is None or session.summary.revision != session.revision:
        raise FramingError("Résumé absent ou obsolète")
    if missing := missing_slots(session):
        raise FramingError(
            "Informations manquantes : " + ", ".join(m.value for m in missing)
        )


def _race(session: FramingSession, candidate: RaceCandidate | None) -> Race:
    summary = session.summary
    distance = (
        _as_float(_slot_value(session, SlotName.distance_km))
        or summary.race.distance_km
    )
    race = summary.race.model_copy(deep=True)
    if candidate is not None:
        sourced = candidate.to_race(distance)
        race.registration_url = race.registration_url or sourced.registration_url
        race.race_date = race.race_date or sourced.race_date
        race.sources = race.sources or sourced.sources
    race.distance_km = distance
    race.race_date = (
        _as_date(_slot_value(session, SlotName.race_date)) or race.race_date
    )
    return race


def _brief(session: FramingSession, race: Race) -> TripBrief:
    summary = session.summary
    arrival, departure = summary.date_range
    if departure < arrival or (departure == arrival and summary.nights):
        raise FramingError(
            "Fenêtre de séjour incohérente : départ avant ou égal à l'arrivée"
        )
    if (departure - arrival).days != summary.nights:
        raise FramingError(
            f"{summary.nights} nuits confirmées mais {(departure - arrival).days} entre les dates"
        )
    preferences = _slot_value(session, SlotName.preferences)
    label = race.name
    if race.race_date and str(race.race_date.year) not in label:
        label = f"{label} {race.race_date.year}"
    return TripBrief(
        race_label=label,
        city=race.city,
        country=race.country,
        race_date=race.race_date,
        distance_km=race.distance_km,
        arrival=arrival,
        departure=departure,
        nights=summary.nights,
        origin=public_origin(summary.origin_public),
        budget_total_eur=summary.budget_eur,
        budget_open=summary.budget_eur is None,
        transport_mode=normalize_transport_mode(summary.transport_mode)
        or summary.transport_mode,
        preferences=str(preferences) if preferences else None,
        hotel_landmarks=[x for x in (race.start_location, race.bib_pickup) if x],
    )


def _merge_limitations(*groups: list[Limitation]) -> list[Limitation]:
    seen: dict[tuple[str, str | None], Limitation] = {}
    for group in groups:
        for limitation in group:
            seen.setdefault((limitation.code, limitation.step), limitation)
    return list(seen.values())


def plan_launch(
    session: FramingSession, profile: RunnerProfile | None = None
) -> LaunchPlan:
    """Plan d'exécution d'un cadrage confirmé ; lève `FramingError` sinon. N'appelle aucun service."""
    _check_confirmed(session)
    profile = profile or RunnerProfile()
    candidate = _selected_candidate(session)
    race = _race(session, candidate)
    brief = _brief(session, race)
    official_url = (
        str(candidate.official_url) if candidate and candidate.official_url else None
    )
    coverages = {
        StepKind.registration: registration_coverage(race, official_url),
        StepKind.accommodation: accommodation_coverage(brief)
        if brief.nights
        else StepCoverage(
            StepKind.accommodation,
            Automation.not_covered,
            limitations=[
                Limitation(
                    code="no_accommodation_requested",
                    message="0 nuit confirmée : aucun hébergement à rechercher.",
                    step=StepKind.accommodation.value,
                )
            ],
        ),
        StepKind.transport: transport_coverage(
            brief.transport_mode, race.country, brief=brief
        ),
    }
    reg, acc, tra = (coverages[k].platform for k in AGENT_STEPS)
    brief.registration_platform = reg.name if reg else None
    brief.accommodation_site = acc.name if acc else None
    brief.accommodation_url = (
        coverages[StepKind.accommodation].start_url if acc else None
    )
    brief.transport_site = tra.name if tra else None
    brief.transport_url = coverages[StepKind.transport].start_url if tra else None

    steps = {}
    for kind, coverage in coverages.items():
        automated = coverage.automation is Automation.automated
        steps[kind] = StepPlan(
            kind=kind,
            automation=coverage.automation,
            platform=coverage.platform.id if coverage.platform else None,
            start_url=coverage.start_url,
            start_url_kind=coverage.start_url_kind,
            task=build_task(kind, race, profile, brief=brief) if automated else None,
            limitations=coverage.limitations,
        )
    limitations = _merge_limitations(
        *(step.limitations for step in steps.values()),
        session.summary.limitations,
        candidate.limitations if candidate else [],
        session.limitations,
    )
    return LaunchPlan(
        framing_id=session.id,
        revision=session.revision,
        mode=session.mode,
        race=race,
        brief=brief,
        steps=steps,
        limitations=limitations,
    )
