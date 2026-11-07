import asyncio
import json
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from runai.contracts.common import Limitation
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
    def __init__(
        self,
        rows=(),
        *,
        error=False,
        responses=None,
        next_edition_responses=None,
    ):
        self.rows = list(rows)
        self.calls = []
        self.error = error
        self.responses = list(responses) if responses is not None else None
        self.next_edition_responses = next_edition_responses or {}

    def search(self, **kwargs):
        self.calls.append((kwargs, threading.get_ident()))
        if self.error:
            raise RuntimeError("supplier unavailable")
        query = kwargs["query"]
        if query.startswith("Find the date of the next edition"):
            name = query.split('of the running race "', 1)[1].split('" in ', 1)[0]
            response = self.next_edition_responses.get(
                name, SimpleNamespace(data={}, sources=[])
            )
            if isinstance(response, Exception):
                raise response
            return response
        rows = self.rows
        if self.responses is not None:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            rows = response
        return SimpleNamespace(data={"candidates": rows}, sources=[
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


def test_city_prompt_allows_a_country_or_region_value():
    client = FakeClient([row(city="Beijing", country="CN")])
    result = asyncio.run(LinkupCandidateSearch(client).search(slots(city="Chine")))

    assert [candidate.city for candidate in result.candidates] == ["Beijing"]
    query = client.calls[0][0]["query"]
    assert '"city_or_region_or_country": "Chine"' in query
    assert '"city": "Chine"' not in query


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


def test_request_text_country_constraint_uses_only_place_in_prompt():
    client = FakeClient([row(city="Beijing", country="CN", distances_km=[21.1])])
    result = asyncio.run(
        LinkupCandidateSearch(client).search(
            slots(distance_km=21.1),
            request_text="Un semi en Chine, mon email a@b.fr",
        )
    )
    assert result.candidates
    assert len(client.calls) == 1
    query = client.calls[0][0]["query"]
    assert 'Location constraint (country or region): "Chine".' in query
    assert "a@b.fr" not in query


def test_request_text_lowercase_month_does_not_trigger_search():
    client = FakeClient()
    result = asyncio.run(
        LinkupCandidateSearch(client).search(
            slots(distance_km=21.1), request_text="un semi en décembre"
        )
    )
    assert result.candidates == []
    assert client.calls == []


@pytest.mark.parametrize(
    "request_text",
    [
        "un semi en Mars",
        "un semi en MARS",
        "un semi in January",
        "un semi in JANUARY",
        "un semi en Lundi",
        "un semi in Wednesday",
    ],
)
def test_location_hint_excludes_months_and_weekdays(request_text):
    assert module.location_hint(request_text) is None


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
    assert len(results) == 5
    assert len(results[0].sources) == 2
    assert results[0].distances_km == [5, 10]
    past = next(candidate for candidate in results if candidate.name == "Past")
    assert past.race_date is None
    assert [limitation.code for limitation in past.limitations] == [
        "next_edition_unconfirmed"
    ]
    undated = next(candidate for candidate in results if candidate.name == "Undated")
    assert undated.race_date is None
    assert undated.limitations[0].code == "race_date_unknown"
    aggregator = next(candidate for candidate in results if candidate.name == "Aggregator")
    assert aggregator.registration_url is None
    assert str(aggregator.limitations[0].manual_url) == "https://official.example/"
    excluded = next(candidate for candidate in results if candidate.name == "Excluded")
    assert excluded.registration_url is None
    assert results[0].id == asyncio.run(search.find_candidates(slots(city="Tokyo")))[0].id


def test_past_edition_is_dropped_when_same_event_has_future_edition():
    client = FakeClient([
        row("Recurring Race", race_date="2020-06-01"),
        row("Recurring Race", race_date="2030-06-01"),
    ])
    results = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).find_candidates(
            slots(city="Tokyo")
        )
    )
    assert len(results) == 1
    assert results[0].race_date == date(2030, 6, 1)
    assert results[0].limitations == []


def test_filtered_future_row_does_not_hide_sourced_past_edition():
    client = FakeClient([
        row("Recurring Race", race_date="2020-06-01"),
        row("Recurring Race", race_date="2030-06-01", source_url=None),
    ])
    results = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).find_candidates(
            slots(city="Tokyo")
        )
    )
    assert len(results) == 1
    assert results[0].race_date is None
    assert [limitation.code for limitation in results[0].limitations] == [
        "next_edition_unconfirmed"
    ]


def test_future_distance_mismatch_hides_past_edition():
    client = FakeClient(responses=[
        [
            row("Recurring Race", race_date="2020-06-01", distances_km=[21.1]),
            row("Recurring Race", race_date="2030-06-01", distances_km=[10]),
        ],
        [],
    ])
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(city="Tokyo", distance_km=21.1)
        )
    )
    assert result.candidates == []
    assert len(client.calls) == 2


def test_next_edition_lookup_updates_past_only_candidate_when_sourced():
    client = FakeClient(
        [row(
            "Past Race",
            race_date="2020-06-01",
            official_url="https://race.example/",
            registration_url="https://race.example/registration/2020",
        )],
        next_edition_responses={
            "Past Race": SimpleNamespace(
                data={
                    "race_date": "2030-06-01",
                    "source_url": "https://race.example/next-edition",
                },
                sources=[],
            )
        },
    )
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(city="Tokyo")
        )
    )
    candidate = result.candidates[0]
    assert candidate.race_date == date(2030, 6, 1)
    assert candidate.registration_url is None
    assert str(candidate.official_url) == "https://race.example/"
    assert "next_edition_unconfirmed" not in {
        limitation.code for limitation in candidate.limitations
    }
    assert "https://race.example/next-edition" in {
        str(source.url) for source in candidate.sources
    }
    lookup = next(
        call[0]
        for call in client.calls
        if call[0]["query"].startswith("Find the date of the next edition")
    )
    assert lookup["depth"] == "standard"
    assert lookup["output_type"] == "structured"
    assert lookup["include_sources"] is True
    assert "https://race.example/" in lookup["query"]


def test_next_edition_lookup_updates_unknown_date_without_clearing_registration_url():
    registration_url = "https://race.example/registration"
    client = FakeClient(
        [row("Undated Race", race_date=None, registration_url=registration_url)],
        next_edition_responses={
            "Undated Race": SimpleNamespace(
                data={
                    "race_date": "2030-06-01",
                    "source_url": "https://race.example/next-edition",
                },
                sources=[],
            )
        },
    )
    candidate = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).find_candidates(
            slots(city="Tokyo")
        )
    )[0]
    assert candidate.race_date == date(2030, 6, 1)
    assert str(candidate.registration_url) == registration_url
    assert not any(
        limitation.code in {"next_edition_unconfirmed", "race_date_unknown"}
        for limitation in candidate.limitations
    )
    assert len(candidate.sources) == 2


def test_next_edition_lookup_prioritizes_past_only_and_caps_total_at_three():
    names = ["Past A", "Past B", "Undated A", "Undated B"]
    rows = [
        row(name, race_date="2020-06-01" if name.startswith("Past") else None)
        for name in names
    ]
    client = FakeClient(
        rows,
        next_edition_responses={
            name: SimpleNamespace(data={}, sources=[]) for name in names
        },
    )
    results = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).find_candidates(
            slots(city="Tokyo")
        )
    )
    lookups = [
        kwargs["query"]
        for kwargs, _ in client.calls
        if kwargs["query"].startswith("Find the date of the next edition")
    ]
    looked_up = [
        query.split('of the running race "', 1)[1].split('" in ', 1)[0]
        for query in lookups
    ]
    assert looked_up == ["Past A", "Past B", "Undated A"]
    assert len(lookups) == 3
    undated_b = next(candidate for candidate in results if candidate.name == "Undated B")
    assert undated_b.race_date is None
    assert undated_b.limitations[0].code == "race_date_unknown"


@pytest.mark.parametrize("outcome", ["empty", "past", "error", "blocked_source"])
def test_next_edition_lookup_failure_or_unverified_data_keeps_candidate(outcome):
    if outcome == "empty":
        response = SimpleNamespace(data={}, sources=[])
    elif outcome == "past":
        response = SimpleNamespace(
            data={
                "race_date": "2020-06-01",
                "source_url": "https://race.example/old",
            },
            sources=[],
        )
    elif outcome == "blocked_source":
        response = SimpleNamespace(
            data={
                "race_date": "2030-06-01",
                "source_url": "https://ahotu.com/race",
            },
            sources=[],
        )
    else:
        response = RuntimeError("next edition unavailable")
    client = FakeClient(
        [row("Past Race", race_date="2020-06-01")],
        next_edition_responses={"Past Race": response},
    )
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(city="Tokyo")
        )
    )
    candidate = result.candidates[0]
    assert candidate.race_date is None
    assert "next_edition_unconfirmed" in {
        limitation.code for limitation in candidate.limitations
    }


def test_only_three_past_only_candidates_get_next_edition_lookups():
    rows = [
        row(f"Past Race {index}", race_date="2020-06-01")
        for index in range(4)
    ]
    client = FakeClient(
        rows,
        next_edition_responses={
            f"Past Race {index}": SimpleNamespace(
                data={
                    "race_date": f"203{index}-06-01",
                    "source_url": f"https://race.example/next-{index}",
                },
                sources=[],
            )
            for index in range(3)
        },
    )
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(city="Tokyo")
        )
    )
    lookups = [
        call
        for call in client.calls
        if call[0]["query"].startswith("Find the date of the next edition")
    ]
    assert len(result.candidates) == 4
    assert len(lookups) == 3
    assert sum(candidate.race_date is not None for candidate in result.candidates) == 3


def test_relaxed_search_runs_once_without_strict_filters_and_marks_close_matches():
    client = FakeClient(responses=[[], [row("Nearby Race", city="Osaka")]])
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(
                city="Tokyo",
                race="Test Race",
                edition="2030",
                race_date="2030-03-10",
                distance_km=20,
                date_window="mars 2030",
            )
        )
    )
    assert len(client.calls) == 2
    assert "distance_km" in client.calls[0][0]["query"]
    assert "2029-01-01" in client.calls[0][0]["query"]
    relaxed_constraints = client.calls[1][0]["query"].split(
        "constraints: ", 1
    )[1].split(". Return", 1)[0]
    assert json.loads(relaxed_constraints) == {
        "city_or_region_or_country": "Tokyo"
    }
    assert "nearby cities (about 50 km)" in client.calls[1][0]["query"]
    assert [candidate.name for candidate in result.candidates] == ["Nearby Race"]
    assert [limitation.code for limitation in result.candidates[0].limitations] == [
        "close_match"
    ]
    assert result.candidates[0].limitations[0].message == (
        "Proche de votre demande, pas exactement ce que vous avez demandé."
    )


def test_relaxed_search_keeps_race_when_city_is_unknown():
    client = FakeClient(responses=[[], [row("Named Race")]])
    result = asyncio.run(
        LinkupCandidateSearch(client).search(
            slots(race="Named Race", distance_km=10)
        )
    )
    assert len(client.calls) == 2
    assert "Named Race" in client.calls[1][0]["query"]
    assert [candidate.name for candidate in result.candidates] == ["Named Race"]


def test_relaxed_empty_search_is_the_only_case_returning_no_candidate_found():
    client = FakeClient(responses=[[], []])
    result = asyncio.run(
        LinkupCandidateSearch(client).search(
            slots(city="Tokyo", edition="2030")
        )
    )
    assert len(client.calls) == 2
    assert result.candidates == []
    assert [limitation.code for limitation in result.limitations] == [
        "no_candidate_found"
    ]


def test_nonempty_strict_search_does_not_retry():
    client = FakeClient(responses=[[row()], [row("Should Not Be Used")]])
    result = asyncio.run(
        LinkupCandidateSearch(client).search(
            slots(city="Tokyo", distance_km=10)
        )
    )
    assert len(client.calls) == 1
    assert [candidate.name for candidate in result.candidates] == ["City Run"]


def test_provider_error_does_not_retry():
    client = FakeClient(error=True)
    with pytest.raises(CandidateSearchError):
        asyncio.run(
            LinkupCandidateSearch(client).search(
                slots(city="Tokyo", distance_km=10)
            )
        )
    assert len(client.calls) == 1


def test_results_are_capped_at_five_with_exact_dated_candidates_first():
    rows = [
        row(f"Race {year}", race_date=f"{year}-06-01")
        for year in (2035, 2034, 2033, 2032, 2031, 2030)
    ]
    rows.append(row("Undated Race", race_date=None))
    client = FakeClient(rows)
    result = asyncio.run(
        LinkupCandidateSearch(client, today=date(2029, 1, 1)).search(
            slots(city="Tokyo", distance_km=10)
        )
    )
    assert [candidate.name for candidate in result.candidates] == [
        "Race 2030",
        "Race 2031",
        "Race 2032",
        "Race 2033",
        "Race 2034",
    ]
    close = result.candidates[0].model_copy(update={
        "limitations": [
            Limitation(
                code="close_match",
                message="Proche de votre demande, pas exactement ce que vous avez demandé.",
            )
        ]
    })
    exact = result.candidates[-1]
    assert LinkupCandidateSearch._rank_candidates([close, exact]) == [exact, close]


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


def test_same_name_and_date_in_different_cities_are_distinct_choices():
    client = FakeClient([row(city="Springfield", country="US"), row(city="Springfield", country="AU"),
                         row(city="Sydney", country="AU")])
    result = asyncio.run(LinkupCandidateSearch(client).find_candidates(slots(race="City Run")))
    assert len(result) == len({r.id for r in result}) == 3


@pytest.mark.parametrize("distances", [[-1], [0], [float("nan")], [float("inf")]])
def test_invalid_distances_do_not_become_sourced_candidates(distances):
    client = FakeClient([row(distances_km=distances)])
    assert asyncio.run(LinkupCandidateSearch(client).find_candidates(slots(city="Tokyo"))) == []
