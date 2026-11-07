from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from runai.contracts.common import Provenance
from runai.contracts.journey import Money
from runai.logistics.models import (
    EntryPath,
    FieldSource,
    RaceRules,
    Requirement,
    RequirementKind,
)
from runai.planning import (
    EligibilityQuestion,
    build_budget,
    eligibility_questions,
    quote_cost_lines,
    rules_cost_lines,
    sheet_limitations,
)
from runai.quote.models import Devis, OptionPayante, Palier
from runai.search.models import Issue, RaceSheet

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def quote(**updates):
    return Devis(plateforme="autre", course="Run", epreuve="10 km", url="https://race.example/",
                 palier_actuel=Palier(prix_eur=30), total_minimal_eur=30, etape_arret="panier",
                 raison_arret="Paiement", rien_soumis=True, **updates)


@pytest.mark.parametrize("source,kind,confidence", [
    ("api", "official_api", "verified"), ("agent_h", "h_agent", "estimated"),
    ("manuel", "human", "estimated"),
])
def test_quote_provenance(source, kind, confidence):
    lines = quote_cost_lines(quote(source=source, frais_inclus_dans_prix=True), now=NOW)
    assert len(lines) == 1
    money = lines[0].money
    assert lines[0].category == "registration"
    assert money.amount == 30 and money.currency == "EUR"
    assert money.collected_at == NOW == money.provenance.collected_at
    assert money.provenance.kind == kind
    assert money.confidence == confidence
    assert str(money.provenance.url) == "https://race.example/"


def test_unknown_prices_not_zero_and_timestamp():
    observed = datetime(2029, 12, 1, tzinfo=UTC)
    lines = quote_cost_lines(quote(releve_le=observed, frais_service_eur=2,
                                  options=[OptionPayante(nom="Pass", obligatoire=True)]), now=NOW)
    assert lines[0].money.collected_at == observed
    assert len(lines) == 3
    assert all(line.money is None and line.note for line in lines[1:])
    budget = build_budget(lines, cap=100)
    assert budget.known_total == 30
    assert budget.complete is False and budget.over_cap is None
    assert {line.category for line in budget.lines} == {"registration", "accommodation", "transport"}


def test_budget_optional_money_and_empty():
    money = Money(amount=20, currency="EUR", collected_at=NOW,
                  provenance=Provenance(kind="human", collected_at=NOW))
    budget = build_budget(quote_cost_lines(quote(frais_inclus_dans_prix=True)),
                          cap=100, accommodation=money, transport=money)
    assert budget.complete and budget.known_total == 70 and budget.over_cap is False
    assert build_budget().complete is False
    assert build_budget().over_cap is None
    with pytest.raises(ValidationError):
        build_budget(transport=money.model_copy(update={"currency": "USD"}))


def rules():
    return RaceRules(race_name="Run", entry_paths=[EntryPath(
        id="visitor", label="Visitor", source=FieldSource(url="https://rules.example/path"),
        requirements=[Requirement(kind=kind, label=kind.value, deadline="Before race",
                                  detail="À fournir par vous", cost_eur=15 if kind == RequirementKind.runcard else None,
                                  source=FieldSource(url="https://rules.example/medical", excerpt="Certificate")
                                  if kind == RequirementKind.medical_certificate else None)
                      for kind in RequirementKind],
    )])


def test_rules_costs_and_human_questions():
    questions = eligibility_questions(rules())
    assert len(questions) == len(RequirementKind)
    assert len({q.id for q in questions}) == len(questions)
    for question in questions:
        assert question.automation == "manual"
        assert "ok" not in question.model_dump()
        assert question.deadline == "Before race"
        assert question.detail == "À fournir par vous"
    medical = next(q for q in questions if q.kind == "medical_certificate")
    assert medical.source_url == "https://rules.example/medical"
    with pytest.raises(ValidationError):
        EligibilityQuestion(id="x", kind="waiver", text="Sign", automation="automated")
    costs = rules_cost_lines(rules(), now=NOW)
    runcard = next(line for line in costs if line.label == "runcard")
    assert runcard.category == "other" and runcard.money.amount == 15
    assert str(runcard.money.provenance.url) == "https://rules.example/path"
    assert runcard.money.provenance.kind == "linkup"
    assert all(line.money is None and line.note for line in costs if line is not runcard)
    assert rules_cost_lines(RaceRules(race_name="Unknown")) == []
    assert eligibility_questions(RaceRules(race_name="Unknown")) == []


def test_sheet_limitations():
    sheet = RaceSheet(query="Run", official_url="https://race.example/", missing_fields=["race_date"],
                      issues=[Issue(field="registration_url", level="warning", message="Not verified")])
    limits = sheet_limitations(sheet)
    assert [limit.code for limit in limits] == ["missing_race_date", "issue_registration_url"]
    assert all(str(limit.manual_url) == "https://race.example/" for limit in limits)
    assert sheet_limitations(RaceSheet(query="Run")) == []


def test_mutually_exclusive_entry_paths_are_not_summed_without_human_choice():
    regulation = RaceRules(race_name="Run", entry_paths=[
        EntryPath(id="licensed", label="Licence", requirements=[
            Requirement(kind="license", label="Licence", cost_eur=0)]),
        EntryPath(id="visitor", label="Visiteur", requirements=[
            Requirement(kind="runcard", label="Carte", cost_eur=15)]),
    ])
    lines = rules_cost_lines(regulation, now=NOW)
    assert all(line.money is None for line in lines)
    assert all("choisir" in line.note for line in lines)
    selected = rules_cost_lines(regulation, entry_path_id="visitor", now=NOW)
    assert len(selected) == 1 and selected[0].money.amount == 15
    with pytest.raises(ValueError, match="inconnue"):
        rules_cost_lines(regulation, entry_path_id="invented", now=NOW)
