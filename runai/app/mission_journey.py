"""Project structured results without geocoding or inferring times from text."""

from copy import deepcopy

from runai.contracts.common import Automation, DataMode, Provenance
from runai.contracts.journey import CostCategory, CostLine, JourneyPlan, Money
from runai.journey import JourneyInputs, Place, build_journey_plan
from runai.journey.planner import PARTIAL_BUDGET_WARNING
from runai.logistics.models import RaceRules
from runai.models import StepKind, StepStatus
from runai.planning.evidence import (
    build_budget,
    eligibility_questions,
    quote_cost_lines,
    rules_cost_lines,
    sheet_limitations,
)
from runai.quote.models import Devis
from runai.search.models import RaceSheet


def _timestamps(value, collected_at):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"provenance", "track_provenance"} and isinstance(item, dict):
                item.setdefault("collected_at", collected_at)
            _timestamps(item, collected_at)
    elif isinstance(value, list):
        for item in value:
            _timestamps(item, collected_at)


def _step_data(step):
    answer = step.data.get("answer")
    return {**answer, **step.data} if isinstance(answer, dict) else step.data


def project_journey(mission):
    summary = mission.framing_summary.model_copy(deep=True)
    summary.limitations = list(mission.limitations)
    mode = mission.plan.mode
    kind = {DataMode.demo: "fixture", DataMode.replay: "replay", DataMode.live: "h_agent"}[mode]
    raw = {"home": {"label": summary.origin_public}, "race": {}}
    prices = {}
    registration = mission.steps[StepKind.registration]
    evidence = _step_data(registration) if registration.status in {StepStatus.completed, StepStatus.stopped_before_commitment} else {}
    for step in mission.steps.values():
        if step.status not in {StepStatus.completed, StepStatus.stopped_before_commitment}:
            continue
        values = _step_data(step).get("journey", {})
        allowed = {
            StepKind.registration: ("race",),
            StepKind.accommodation: ("hotel",),
            StepKind.transport: ("home", "outbound", "return_trip", "local_cost"),
        }[step.kind]
        raw.update({key: deepcopy(values[key]) for key in allowed if key in values})
        if step.price_eur is not None:
            prices[step.kind] = Money(
                amount=step.price_eur, currency="EUR", collected_at=mission.created_at,
                provenance=Provenance(kind=kind, url=step.url, collected_at=mission.created_at),
            )
    if not isinstance(raw["home"], dict) or not isinstance(raw["race"], dict):
        raise TypeError("Invalid structured place or race")
    raw["home"]["label"] = summary.origin_public
    _timestamps(raw, mission.created_at)
    if raw.get("hotel"):
        raw["hotel"] = {"check_in_from": None, "check_out_until": None, **raw["hotel"]}
    if raw["race"].get("rules") and "timezone" not in raw["race"]["rules"]:
        raise ValueError("Rules lack a timezone: cannot interpret the time")
    inputs = JourneyInputs.model_validate(raw)
    if inputs.race.track:
        inputs.race.track_provenance = Provenance(kind=kind, collected_at=mission.created_at)
    for leg in (inputs.outbound, inputs.return_trip):
        if leg and leg.geometry:
            leg.geometry_verified = False
            leg.provenance = Provenance(kind=kind, collected_at=mission.created_at)
        if leg and (leg.mode != "train" or mission.plan.steps[StepKind.transport].automation is not Automation.automated):
            leg.automation = Automation.manual
    if inputs.hotel and mission.plan.steps[StepKind.accommodation].automation is not Automation.automated:
        inputs.hotel.automation = Automation.manual
    if inputs.race.start is None and summary.race.start_location:
        inputs.race.start = Place(label=summary.race.start_location)
    inputs.race.registration_url = inputs.race.registration_url or summary.race.registration_url
    inputs.race.registration_cost = inputs.race.registration_cost or prices.get(StepKind.registration)
    if inputs.hotel:
        inputs.hotel.cost = inputs.hotel.cost or prices.get(StepKind.accommodation)
    rules = None
    if evidence.get("rules"):
        if "timezone" not in evidence["rules"]:
            raise ValueError("Rules lack a timezone: cannot interpret the time")
        rules = RaceRules.model_validate(evidence["rules"])
        inputs.race.rules = rules
    elif inputs.race.rules:
        rules = inputs.race.rules
    if evidence.get("race_sheet"):
        summary.limitations.extend(sheet_limitations(RaceSheet.model_validate(evidence["race_sheet"])))
    plan = build_journey_plan(summary, inputs, mission_id=mission.id, mode=mode, previous=mission.journey)
    lines = list(plan.budget.lines)
    if evidence.get("quote"):
        lines = [line for line in lines if line.category is not CostCategory.registration]
        lines.extend(quote_cost_lines(Devis.model_validate(evidence["quote"]),
                                      evidence.get("chosen_options", ()), now=mission.created_at))
    if rules:
        lines.extend(rules_cost_lines(rules, entry_path_id=evidence.get("entry_path_id"), now=mission.created_at))
    for category, step_kind in ((CostCategory.accommodation, StepKind.accommodation),
                                (CostCategory.transport, StepKind.transport)):
        if step_kind in prices and not any(line.money for line in lines if line.category is category):
            lines = [line for line in lines if line.category is not category]
            lines.append(CostLine(id=f"step-{category.value}", category=category,
                                  label=f"{category.value} (step total)", money=prices[step_kind],
                                  note="Choice details are still incomplete."))
    plan.budget = build_budget(lines, cap=summary.budget_eur)
    plan.warnings = [warning for warning in plan.warnings if warning != PARTIAL_BUDGET_WARNING]
    if not plan.budget.complete:
        plan.warnings.append(PARTIAL_BUDGET_WARNING)
    for line in plan.budget.lines:
        if line.money:
            provenance = line.money.provenance
            if mode is DataMode.live and provenance.kind.value in {"fixture", "replay"}:
                raise ValueError("Simulated evidence rejected in a live trip")
            if provenance not in plan.sources:
                plan.sources.append(provenance)
    previous = mission.journey
    if previous:
        same = plan.model_dump(exclude={"revision"}) == previous.model_dump(exclude={"revision"})
        plan.revision = previous.revision if same else previous.revision + 1
    return JourneyPlan.model_validate(plan.model_dump()), eligibility_questions(rules) if rules else []
