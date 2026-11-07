"""Bounded, parallel Linkup discovery before browser agents launch."""

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlsplit

from linkup import LinkupSearchTaskInput
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from runai.app.providers import FORBIDDEN_HOSTS
from runai.app.tasks import TripBrief
from runai.models import Race
from runai.search.checks import host_of, is_aggregator, on_domain


class Hotel(BaseModel):
    name: str
    official_url: HttpUrl
    distance_km: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_url: HttpUrl | None = None


class TransportOperator(BaseModel):
    name: str
    official_url: HttpUrl
    mode: str


class LogisticsSweep(BaseModel):
    race_form_url: HttpUrl | None = None
    hotels: list[Hotel] = Field(default_factory=list, max_length=5)
    transport_operators: list[TransportOperator] = Field(default_factory=list)
    latency_s: float = 0
    calls: int = 0
    estimated_cost_usd: float = 0
    source_urls: list[HttpUrl] = Field(default_factory=list)


def _safe_url(value: Any) -> bool:
    host = host_of(value)
    return bool(host) and not is_aggregator(host) and not any(
        on_domain(host, forbidden) for forbidden in FORBIDDEN_HOSTS
    )


def _clean(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower().startswith("not provided"):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _schema(fields: dict) -> dict:
    return {"type": "object", "properties": fields}


def _field(kind: str, description: str) -> dict:
    return {"type": kind, "description": description + "; omit if unknown"}


HOTELS_SCHEMA = _schema({
    "race_form_url": _field("string", "Race-specific registration form on the registration platform, not the event homepage"),
    "hotels": {"type": "array", "maxItems": 5, "items": _schema({
        "name": _field("string", "Hotel name"),
        "official_url": _field("string", "Hotel's own official website, no aggregators"),
        "distance_km": _field("number", "Distance from race start in km"),
        "source_url": _field("string", "Official source URL"),
    })},
})
TRANSPORT_SCHEMA = _schema({
    "transport_operators": {"type": "array", "items": _schema({
        "name": _field("string", "Operator serving the requested route"),
        "official_url": _field("string", "Operator's official website"),
        "mode": _field("string", "Transport mode"),
    })},
})


async def sweep_logistics(race: Race, brief: TripBrief, client, timeout_s=15) -> LogisticsSweep:
    started = time.monotonic()
    calls = 0
    queries = [
        ((f"Find the race-specific registration platform form for {race.name} {race.race_date or ''} "
         f"(known registration URL: {race.registration_url}). Also find hotels near "
         f"{race.start_location or race.city}, {race.city}. Maximum 5 hotels, official websites only, "
         "no aggregators. Omit unknown fields."), HOTELS_SCHEMA),
        ((f"Find official transport operators from {brief.origin} to {race.city}, {race.country}, "
         f"preferred mode {brief.transport_mode or 'any'}. No aggregators. Omit unknown fields."), TRANSPORT_SCHEMA),
    ]

    async def poll(task):
        while task.status in {"pending", "processing"}:
            await asyncio.sleep(1)
            task = await asyncio.to_thread(client.get_task, task.id)
        if task.status != "completed":
            raise RuntimeError("Linkup task failed")
        return task.output

    async def search():
        nonlocal calls
        try:
            calls += len(queries)
            tasks = await asyncio.to_thread(client.create_tasks, [
                LinkupSearchTaskInput(q=q, depth="standard", output_type="structured",
                                      structured_output_schema=schema)
                for q, schema in queries
            ])
            if len(tasks) != len(queries):
                raise RuntimeError("Incomplete Linkup batch")
            return await asyncio.gather(*(poll(task) for task in tasks))
        except Exception:  # noqa: BLE001 - SDK task failures use synchronous search as fallback
            calls += len(queries)
            return await asyncio.gather(*(
                asyncio.to_thread(client.search, query=q, depth="standard", output_type="structured",
                                  structured_output_schema=schema)
                for q, schema in queries
            ))

    try:
        async with asyncio.timeout(timeout_s):
            outputs = await search()
    except TimeoutError:
        return LogisticsSweep(latency_s=round(time.monotonic() - started, 3))
    data = {}
    for output in outputs:
        if isinstance(output, BaseModel):
            output = output.model_dump()
        if isinstance(output, str):
            output = json.loads(output)
        data.update(_clean(output or {}))
    result = LogisticsSweep(latency_s=round(time.monotonic() - started, 3), calls=calls,
                            estimated_cost_usd=round(calls * 0.015, 3))
    form = data.get("race_form_url")
    if form and _safe_url(form) and urlsplit(form).path.strip("/"):
        try:
            result.race_form_url = LogisticsSweep(race_form_url=form).race_form_url
        except ValidationError:
            pass
    for key, model in (("hotels", Hotel), ("transport_operators", TransportOperator)):
        for item in data.get(key) or []:
            try:
                parsed = model.model_validate(item)
            except ValidationError:
                continue
            if not _safe_url(parsed.official_url):
                continue
            if isinstance(parsed, Hotel) and parsed.source_url and not _safe_url(parsed.source_url):
                continue
            target = getattr(result, key)
            if key != "hotels" or len(target) < 5:
                target.append(parsed)
    urls = [result.race_form_url]
    urls += [url for hotel in result.hotels for url in (hotel.official_url, hotel.source_url)]
    urls += [operator.official_url for operator in result.transport_operators]
    result.source_urls = list(dict.fromkeys(url for url in urls if url))
    return result


class LinkupLogisticsSweeper:
    def __init__(self, client):
        self.client = client

    async def sweep(self, race: Race, brief: TripBrief, timeout_s=15) -> LogisticsSweep:
        return await sweep_logistics(race, brief, self.client, timeout_s)
