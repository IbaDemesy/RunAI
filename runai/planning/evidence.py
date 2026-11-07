"""Adaptation des preuves de prix et des démarches humaines au séjour."""

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from runai.contracts.common import (
    Automation,
    Confidence,
    Limitation,
    Provenance,
    ProvenanceKind,
)
from runai.contracts.journey import Budget, CostCategory, CostLine, Money
from runai.logistics.models import RaceRules, RequirementKind
from runai.models import utcnow
from runai.quote.cost import registration_lines
from runai.quote.models import Devis
from runai.search.models import RaceSheet


class EligibilityQuestion(BaseModel):
    id: str
    kind: RequirementKind
    text: str
    detail: str | None = None
    deadline: str | None = None
    source_url: str | None = None
    automation: Literal[Automation.manual] = Automation.manual


def quote_cost_lines(devis: Devis, options_choisies: Iterable[str] = (), *,
                     now: datetime | None = None) -> list[CostLine]:
    at = devis.releve_le or now or utcnow()
    kind = {"api": ProvenanceKind.official_api, "agent_h": ProvenanceKind.h_agent,
            "manuel": ProvenanceKind.human}[devis.source]
    provenance = Provenance(kind=kind, url=devis.url, collected_at=at)
    lines, alerts = registration_lines(devis, options_choisies)
    result = [CostLine(
        id=f"registration-{i}", category=CostCategory.registration, label=line.poste,
        money=Money(amount=line.eur, currency="EUR", collected_at=at, provenance=provenance,
                    confidence=Confidence.verified if line.source == "mesure" else Confidence.estimated),
        note=line.note or None,
    ) for i, line in enumerate(lines)]
    result.extend(CostLine(id=f"registration-unknown-{i}", category=CostCategory.registration,
                           label="Prix à confirmer", note=alert) for i, alert in enumerate(alerts))
    if devis.frais_service_eur is None and devis.frais_inclus_dans_prix is not True:
        result.append(CostLine(id="registration-fees-unknown", category=CostCategory.registration,
                               label="Frais de service", note="Montant ou inclusion des frais non confirmé."))
    return result


def _requirements(rules: RaceRules):
    for path in rules.entry_paths:
        for i, requirement in enumerate(path.requirements):
            source = requirement.source or path.source or rules.field_sources.get("entry_paths")
            yield f"requirement-{path.id}-{i}", requirement, source


def rules_cost_lines(rules: RaceRules, *, now: datetime | None = None) -> list[CostLine]:
    at = now or utcnow()
    out = []
    for identifier, requirement, source in _requirements(rules):
        provenance = Provenance(
            kind=ProvenanceKind.fixture if rules.origin == "fixture" else ProvenanceKind.linkup,
            url=source.url if source else rules.regulation_url,
            label=source.excerpt if source else None, collected_at=at,
        )
        out.append(CostLine(
            id=identifier, category=CostCategory.other, label=requirement.label,
            money=Money(amount=requirement.cost_eur, currency="EUR", collected_at=at,
                        provenance=provenance, confidence=Confidence.estimated)
            if requirement.cost_eur is not None else None,
            note=requirement.detail if requirement.cost_eur is not None else "Coût non publié, à confirmer.",
        ))
    return out


def build_budget(lines: Iterable[CostLine] = (), *, cap: float | None = None,
                 accommodation: Money | None = None, transport: Money | None = None) -> Budget:
    result = list(lines)
    for category, money in ((CostCategory.registration, None),
                            (CostCategory.accommodation, accommodation), (CostCategory.transport, transport)):
        if money is not None:
            result.append(CostLine(id=f"{category.value}-provided", category=category,
                                   label=category.value, money=money))
        elif not any(line.category == category for line in result):
            result.append(CostLine(id=f"{category.value}-unknown", category=category,
                                   label=category.value, note="Prix non renseigné."))
    return Budget(cap=cap, lines=result)


def eligibility_questions(rules: RaceRules) -> list[EligibilityQuestion]:
    return [EligibilityQuestion(
        id=identifier, kind=requirement.kind, text=requirement.label,
        detail=requirement.detail, deadline=requirement.deadline,
        source_url=str(source.url) if source else str(rules.regulation_url) if rules.regulation_url else None,
    ) for identifier, requirement, source in _requirements(rules)]


def sheet_limitations(sheet: RaceSheet) -> list[Limitation]:
    return [Limitation(code=f"missing_{field}", message=f"Information non trouvée : {field}",
                       manual_url=sheet.official_url) for field in sheet.missing_fields] + [
        Limitation(code=f"issue_{issue.field}", message=issue.message, manual_url=sheet.official_url)
        for issue in sheet.issues
    ]
