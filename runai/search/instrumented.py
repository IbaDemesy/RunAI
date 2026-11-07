"""Thread-safe Linkup call estimates, scoped to a single candidate search."""

import json
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel, HttpUrl, TypeAdapter, ValidationError

from runai.coach.finder import PRICE_SEARCH_STANDARD
from runai.contracts.framing import LinkupCall, SearchStats
from runai.search.linkup_search import SearchClient

PRICE_SEARCH_DEEP = 0.055
PRICE_FETCH = 0.005
_URL = TypeAdapter(HttpUrl)


def _source_urls(response: Any) -> list[HttpUrl]:
    urls: dict[str, HttpUrl] = {}

    def add(value: Any) -> None:
        try:
            url = _URL.validate_python(value)
        except ValidationError:
            return
        urls[str(url)] = url

    def walk(value: Any) -> None:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_url":
                    add(item)
                elif key in ("sources", "results") and isinstance(item, list):
                    for source in item:
                        add(source.get("url") if isinstance(source, dict)
                            else getattr(source, "url", source))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    if not isinstance(response, (dict, BaseModel, str, list)):
        response = {key: getattr(response, key, None) for key in ("sources", "results", "data")}
    walk(response)
    return list(urls.values())


class InstrumentedSearchClient:
    def __init__(self, client: SearchClient):
        self._client = client
        self._calls: list[LinkupCall] = []
        self._lock = threading.Lock()

    @property
    def stats(self) -> SearchStats:
        with self._lock:
            calls = [call.model_copy(deep=True) for call in self._calls]
        return SearchStats(
            calls=calls,
            total_latency_ms=sum(call.latency_ms for call in calls),
            estimated_cost_usd=round(sum(call.estimated_cost_usd for call in calls), 6),
            source_count=sum(call.source_count for call in calls),
            domains=list(dict.fromkeys(domain for call in calls for domain in call.domains)),
        )

    def search(self, query: str, **kwargs: Any) -> Any:
        return self._call("search", query, **kwargs)

    def fetch(self, url: str, **kwargs: Any) -> Any:
        return self._call("fetch", url, **kwargs)

    def _call(self, endpoint: Literal["search", "fetch"], query: str, **kwargs: Any) -> Any:
        started = time.perf_counter()
        response = None
        try:
            if endpoint == "search":
                response = self._client.search(query=query, **kwargs)
            else:
                response = self._client.fetch(url=query, **kwargs)
            return response
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            urls = _source_urls(response)
            if endpoint == "fetch" and response is not None:
                urls = _source_urls({"sources": [query, *urls]})
            depth = kwargs.get("depth", "standard") if endpoint == "search" else None
            call = LinkupCall(
                endpoint=endpoint,
                depth=depth,
                output_type=kwargs.get("output_type"),
                query=query[:200],
                latency_ms=latency_ms,
                source_count=len(urls),
                domains=list(dict.fromkeys(url.host for url in urls if url.host)),
                estimated_cost_usd=(PRICE_FETCH if endpoint == "fetch" else
                                    PRICE_SEARCH_DEEP if depth == "deep" else PRICE_SEARCH_STANDARD),
            )
            with self._lock:
                self._calls.append(call)
