import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from runai.search import instrumented


class FakeClient:
    def search(self, query, **kwargs):
        if query == "fail":
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(
            data=json.dumps({"candidates": [{"source_url": "https://race.example/date"}]}),
            sources=[
                {"url": "https://race.example/date"},
                SimpleNamespace(url="https://info.example/race"),
                {"url": "https://race.example/rules"},
                {"url": "not a URL"},
            ],
        )

    def fetch(self, url, **kwargs):
        return {"markdown": "Official race details"}


def test_records_calls_and_aggregates_cost_latency_and_source_domains(monkeypatch):
    ticks = iter([1.0, 1.125, 2.0, 2.5, 3.0, 3.025])
    monkeypatch.setattr(instrumented.time, "perf_counter", lambda: next(ticks))
    client = instrumented.InstrumentedSearchClient(FakeClient())
    response = client.search("x" * 250, depth="standard", output_type="structured")
    assert response.data
    client.search(query="next edition", depth="deep", output_type="sourcedAnswer")
    client.fetch("https://race.example/rules", render_js=True)

    stats = client.stats
    assert stats.provider == "linkup"
    assert [call.endpoint for call in stats.calls] == ["search", "search", "fetch"]
    assert [call.depth for call in stats.calls] == ["standard", "deep", None]
    assert [call.output_type for call in stats.calls] == ["structured", "sourcedAnswer", None]
    assert stats.calls[0].query == "x" * 200
    assert stats.calls[2].query == "https://race.example/rules"
    assert [call.latency_ms for call in stats.calls] == pytest.approx([125, 500, 25])
    assert stats.total_latency_ms == pytest.approx(650)
    assert [call.source_count for call in stats.calls] == [3, 3, 1]
    assert stats.source_count == 7
    assert stats.domains == ["race.example", "info.example"]
    assert stats.calls[0].domains == ["race.example", "info.example"]
    assert [call.estimated_cost_usd for call in stats.calls] == [0.006, 0.055, 0.005]
    assert stats.estimated_cost_usd == pytest.approx(0.066)


def test_failed_calls_are_recorded_without_swallowing_the_provider_error():
    client = instrumented.InstrumentedSearchClient(FakeClient())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        client.search("fail", depth="standard", output_type="structured")
    stats = client.stats
    assert len(stats.calls) == 1
    assert stats.calls[0].latency_ms > 0
    assert stats.source_count == 0
    assert stats.domains == []
    assert stats.estimated_cost_usd == 0.006


def test_parallel_calls_are_not_lost_and_snapshots_are_independent():
    client = instrumented.InstrumentedSearchClient(FakeClient())
    before = client.stats
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: client.search(str(i), depth="standard"), range(20)))
    stats = client.stats
    assert len(stats.calls) == 20
    assert all(call.latency_ms > 0 for call in stats.calls)
    assert stats.estimated_cost_usd == pytest.approx(0.12)
    assert before.calls == []
    stats.calls[0].query = "changed"
    stats.domains.clear()
    assert client.stats.calls[0].query != "changed"
    assert client.stats.domains == ["race.example", "info.example"]


@pytest.mark.parametrize("as_model", [False, True])
def test_structured_citations_without_top_level_sources_are_counted(as_model):
    class Edition(BaseModel):
        source_url: str

    class Client(FakeClient):
        def search(self, query, **kwargs):
            data = {"source_url": "https://official.example/next"}
            return SimpleNamespace(data=Edition(**data) if as_model else data)

    client = instrumented.InstrumentedSearchClient(Client())
    client.search("next edition", depth="standard", output_type="structured")
    assert client.stats.source_count == 1
    assert client.stats.domains == ["official.example"]


def test_search_results_and_missing_citations():
    class Client(FakeClient):
        def search(self, query, **kwargs):
            if query == "empty":
                return {"data": "not JSON"}
            return {"results": [{"url": "https://RESULT.example/a"}, {"url": "https://result.example/a"}]}

    client = instrumented.InstrumentedSearchClient(Client())
    client.search("race", depth="standard", output_type="searchResults")
    client.search("empty", depth="standard", output_type="structured")
    assert [call.source_count for call in client.stats.calls] == [1, 0]
    assert client.stats.domains == ["result.example"]
