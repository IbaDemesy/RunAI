"""Cited Linkup answers restricted to a race's official domains, for H agents and the live view."""

import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from runai.models import Race
from runai.search.checks import host_of, is_aggregator, on_domain
from runai.search.linkup_search import SearchClient

AnswerDepth = Literal["standard", "deep"]

# Linkup list price per call: EUR 5 / 1,000 standard, EUR 50 / 1,000 deep (~1.1 USD per EUR).
COST_USD = {"standard": 0.0055, "deep": 0.055}

_CITATION = re.compile(r"\[(\d{1,2})\]")
MAX_UNCITED_SOURCES = 3


class Citation(BaseModel):
    index: int
    url: str
    title: str | None = None


class SourcedAnswer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    latency_s: float
    estimated_cost_usd: float


def official_domains(race: Race) -> list[str]:
    """Hosts of the race's own sources and registration page, never aggregators."""
    urls = [source.url for source in race.sources]
    if race.registration_url is not None:
        urls.append(race.registration_url)
    hosts = (host_of(url) for url in urls)
    return list(dict.fromkeys(host for host in hosts if host and not is_aggregator(host)))


def build_question(race: Race, question: str) -> str:
    details = ", ".join(
        part
        for part in (race.city, race.race_date.isoformat() if race.race_date else None)
        if part
    )
    context = f" ({details})" if details else ""
    return (
        f'For the running race "{race.name}"{context}: {question.strip()} '
        "Answer only from the official race pages (regulations, FAQ, practical info) and cite them. "
        "If the official pages do not say, answer that it is not published: never guess."
    )


def _citations(response: Any, answer: str, domains: list[str]) -> list[Citation]:
    """Sources referenced by the inline [n] markers (1-based), or the first few if none are cited."""
    cited = {int(match) for match in _CITATION.findall(answer)}
    citations: list[Citation] = []
    for index, source in enumerate(getattr(response, "sources", None) or [], start=1):
        url = getattr(source, "url", None)
        if not url or not any(on_domain(host_of(url), domain) for domain in domains):
            continue
        if cited and index not in cited:
            continue
        citations.append(Citation(index=index, url=url, title=getattr(source, "name", None) or None))
    return citations if cited else citations[:MAX_UNCITED_SOURCES]


def answer_official(
    question: str,
    official_domains: list[str],
    client: SearchClient,
    depth: AnswerDepth = "standard",
    *,
    race: Race | None = None,
) -> SourcedAnswer | None:
    """Ask Linkup for a cited answer from the official domains only; None when no official domain is known."""
    domains = [domain for domain in dict.fromkeys(official_domains) if domain and not is_aggregator(domain)]
    if not domains:
        return None
    started = time.perf_counter()
    response = client.search(
        query=build_question(race, question) if race else question,
        depth=depth,
        output_type="sourcedAnswer",
        include_inline_citations=True,
        include_sources=True,
        include_domains=domains,
    )
    latency_s = round(time.perf_counter() - started, 2)
    answer = (getattr(response, "answer", "") or "").strip()
    return SourcedAnswer(
        question=question,
        answer=answer,
        citations=_citations(response, answer, domains),
        domains=domains,
        latency_s=latency_s,
        estimated_cost_usd=COST_USD[depth],
    )


def format_for_agent(answer: SourcedAnswer) -> str:
    lines = [answer.answer or "The official pages returned no answer."]
    if answer.citations:
        lines.append("Sources:")
        lines += [f"[{citation.index}] {citation.url}" for citation in answer.citations]
    return "\n".join(lines)
