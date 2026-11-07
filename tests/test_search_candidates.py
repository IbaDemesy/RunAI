import asyncio
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from runai.contracts.framing import Slot, SlotName, SlotStatus
from runai.search import candidates as module
from runai.search.candidates import CandidateSearchError, LinkupCandidateSearch
from runai.search.linkup_search import default_client


def slots(**values):
    return {SlotName(k): Slot(name=SlotName(k), status=SlotStatus.answered, value=v)
            for k, v in values.items()}


def row(name="City Run", **kwargs):
    return {"name": name, "city": "Tokyo", "country": "JP", "race_date": "2030-06-01",
            "distances_km": [10], "source_url": "https://race.example/facts", **kwargs}


class FakeClient:
    def __init__(self, rows=(), *, error=False):
        self.rows = list(rows)
        self.calls = []
        self.error = error

    def search(self, **kwargs):
        self.calls.append((kwargs, threading.get_ident()))
        if self.error:
            raise RuntimeError("supplier unavailable")
        return SimpleNamespace(data={"candidates": self.rows}, sources=[
            {"url": "https://race.example/facts", "title": "Official facts"},
            {"url": "https://unrelated.example/"},
        ])

    def fetch(self, **kwargs):
        raise AssertionError("fetch unexpected")


@pytest.fixture(autouse=True)
def forbid_default(monkeypatch):
    def fail():
        raise AssertionError("default client unexpectedly constructed")
    monkeypatch.setattr(module, "default_client", fail)


@pytest.mark.parametrize("city", ["Tokyo", "Nairobi", "Lisbonne", "Valparaiso"])
def test_generic_candidates(city):
    client = FakeClient([row(city=city), row("River Run", city=city, distances_km=[5])])
    result = asyncio.run(LinkupCandidateSearch(client).search(slots(city=city)))
    assert len(result.candidates) == 2
    first, second = result.candidates
    assert first.id != second.id
    assert first.city == city
    assert first.race_date == date(2030, 6, 1)
    assert first.provenance.kind == "linkup"
    assert first.provenance.url == first.sources[0].url
    assert len(first.sources) == 1
    assert "unrelated" not in str(first.sources)
    prompt = client.calls[0][0]["query"]
    assert city in prompt
    assert "marathon" not in prompt.lower()
    assert "2030" not in prompt
    assert "origin" not in prompt
    assert client.calls[0][1] != threading.get_ident()


def test_only_known_slots_and_no_location():
    unknown = slots(city="Lisbonne")
    unknown[SlotName.race] = Slot(name=SlotName.race, value="invented marathon")
    unknown[SlotName.origin] = Slot(name=SlotName.origin, status="answered", value="Paris")
    client = FakeClient()
    asyncio.run(LinkupCandidateSearch(client).find_candidates(unknown))
    assert "invented" not in client.calls[0][0]["query"]
    assert "Paris" not in client.calls[0][0]["query"]
    assert client.calls[0][0]["include_sources"] is True
    assert "marathon" not in client.calls[0][0]["query"].lower()
    result = asyncio.run(LinkupCandidateSearch().search({}))
    assert result.candidates == []
    assert result.limitations[0].code == "no_candidate_found"


def test_empty_and_errors(monkeypatch):
    result = asyncio.run(LinkupCandidateSearch(FakeClient()).search(slots(city="Tokyo")))
    assert not result.candidates
    assert result.limitations[0].code == "no_candidate_found"
    with pytest.raises(CandidateSearchError):
        asyncio.run(LinkupCandidateSearch(FakeClient(error=True)).search(slots(race="Run")))
    monkeypatch.setattr(module, "default_client", default_client)
    monkeypatch.setattr("runai.search.linkup_search.get_settings", lambda: SimpleNamespace(linkup_api_key=None))
    with pytest.raises(CandidateSearchError) as exc:
        asyncio.run(LinkupCandidateSearch().search(slots(city="Tokyo")))
    assert "LINKUP_API_KEY" in str(exc.value.__cause__)


def test_filter_merge_dates_and_registration():
    client = FakeClient([
        row(), row(source_url="https://race.example/extra", distances_km=[5, 10]),
        row("Unsourced", source_url=None), row("Past", race_date="2020-01-01"),
        row("Undated", race_date=None),
        row("Aggregator", official_url="https://official.example/", registration_url="https://ahotu.com/run"),
        row("Excluded", registration_url="https://finishers.com/run"),
    ])
    search = LinkupCandidateSearch(client, today=date(2029, 1, 1))
    results = asyncio.run(search.find_candidates(slots(city="Tokyo")))
    assert len(results) == 4
    assert len(results[0].sources) == 2
    assert results[0].distances_km == [5, 10]
    assert results[1].race_date is None
    assert results[1].limitations[0].code == "race_date_unknown"
    assert results[2].registration_url is None
    assert str(results[2].limitations[0].manual_url) == "https://official.example/"
    assert results[3].registration_url is None
    assert results[0].id == asyncio.run(search.find_candidates(slots(city="Tokyo")))[0].id


def test_distance_only_when_known():
    client = FakeClient([row(), row("Five", distances_km=[5]), row("Unknown", distances_km=[])])
    assert len(asyncio.run(LinkupCandidateSearch(client).find_candidates(slots(city="Tokyo")))) == 3
    result = asyncio.run(LinkupCandidateSearch(client).find_candidates(slots(city="Tokyo", distance_km=10)))
    assert [r.name for r in result] == ["City Run", "Unknown"]


def test_invalid_provider_payload():
    client = FakeClient()
    client.search = lambda **kwargs: {"unexpected": []}
    with pytest.raises(CandidateSearchError):
        asyncio.run(LinkupCandidateSearch(client).search(slots(city="Tokyo")))
