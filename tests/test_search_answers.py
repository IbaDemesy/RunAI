from datetime import date
from types import SimpleNamespace

import pytest

from runai.models import Race, Source
from runai.search import SourcedAnswer, answer_official, official_domains
from runai.search.answers import COST_USD, build_question, format_for_agent

OFFICIAL = "https://www.example-marathon.org"


class FakeClient:
    def __init__(self, answer="", sources=()):
        self.calls = []
        self.response = SimpleNamespace(
            answer=answer,
            sources=[SimpleNamespace(name=name, url=url, snippet="") for name, url in sources],
        )

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.response


def race(**overrides):
    values = {
        "name": "Example City Marathon 2027",
        "city": "Example City",
        "country": "FR",
        "race_date": date(2027, 4, 11),
        "registration_url": "https://in.njuko.com/example-marathon-2027",
        "sources": [
            Source(url=f"{OFFICIAL}/en/", title="Official"),
            Source(url="https://www.ahotu.com/event/example-marathon", title="Aggregator"),
            Source(url=f"{OFFICIAL}/en/faq", title="FAQ"),
        ],
    }
    return Race(**{**values, **overrides})


def test_official_domains_keep_race_and_registration_hosts_but_never_aggregators():
    assert official_domains(race()) == ["example-marathon.org", "in.njuko.com"]
    assert official_domains(race(sources=[], registration_url=None)) == []
    only_aggregator = race(
        sources=[Source(url="https://www.worldsmarathons.com/marathon/example")],
        registration_url=None,
    )
    assert official_domains(only_aggregator) == []


def test_answer_parses_inline_citations_and_restricts_to_official_domains():
    client = FakeClient(
        answer="A PPS or an FFA licence is required.[2][4]",
        sources=[
            ("Home", f"{OFFICIAL}/en/"),
            ("Medical certificate", f"{OFFICIAL}/en/information/medical-certificate"),
            ("Blog", "https://running-blog.example.net/pps"),
            ("Registration", "https://in.njuko.com/example-marathon-2027"),
        ],
    )

    answer = answer_official(
        "Is a medical certificate required?",
        ["example-marathon.org", "in.njuko.com", "ahotu.com"],
        client,
    )

    assert isinstance(answer, SourcedAnswer)
    assert answer.question == "Is a medical certificate required?"
    assert answer.answer.startswith("A PPS")
    assert [(c.index, c.url, c.title) for c in answer.citations] == [
        (2, f"{OFFICIAL}/en/information/medical-certificate", "Medical certificate"),
        (4, "https://in.njuko.com/example-marathon-2027", "Registration"),
    ]
    assert answer.domains == ["example-marathon.org", "in.njuko.com"]
    query, kwargs = client.calls[0]
    assert query == "Is a medical certificate required?"
    assert kwargs == {
        "depth": "standard",
        "output_type": "sourcedAnswer",
        "include_inline_citations": True,
        "include_sources": True,
        "include_domains": ["example-marathon.org", "in.njuko.com"],
    }


def test_answer_without_markers_keeps_only_a_few_official_sources():
    sources = [(f"Page {n}", f"{OFFICIAL}/p/{n}") for n in range(1, 6)]
    answer = answer_official("Bib pick-up hours?", ["example-marathon.org"], FakeClient("Friday 10-20.", sources))

    assert [c.index for c in answer.citations] == [1, 2, 3]


@pytest.mark.parametrize("domains", [[], ["ahotu.com"], [""]])
def test_answer_is_none_without_official_domain_and_never_searches(domains):
    client = FakeClient("should not be used")

    assert answer_official("Cut-off time?", domains, client) is None
    assert client.calls == []


@pytest.mark.parametrize("depth", ["standard", "deep"])
def test_answer_reports_cost_and_latency(monkeypatch, depth):
    ticks = iter([10.0, 13.3])
    monkeypatch.setattr("runai.search.answers.time.perf_counter", lambda: next(ticks))

    answer = answer_official("Fees?", ["example-marathon.org"], FakeClient("EUR 120.[1]", [("Fees", OFFICIAL)]), depth)

    assert answer.latency_s == pytest.approx(3.3)
    assert answer.estimated_cost_usd == COST_USD[depth] > 0
    assert format_for_agent(answer) == f"EUR 120.[1]\nSources:\n[1] {OFFICIAL}"


def test_race_context_is_added_to_the_linkup_query_only():
    client = FakeClient("Not published.")

    answer = answer_official("Cut-off time?", ["example-marathon.org"], client, race=race())

    query, _ = client.calls[0]
    assert query == build_question(race(), "Cut-off time?")
    assert '"Example City Marathon 2027" (Example City, 2027-04-11): Cut-off time?' in query
    assert "never guess" in query
    assert answer.question == "Cut-off time?"
    assert answer.citations == []
