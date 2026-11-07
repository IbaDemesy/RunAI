"""Devis d'inscription (Njuko, Klikego en lecture) et coût total du week-end.

    from runai.quote import fetch_njuko_quote, weekend_cost, verifier_prix

    devis = fetch_njuko_quote("wizz-air-milano-marathon-20271776152378557", "non comp")
    cout = weekend_cost(devis, ["assurance d'annulation"], hotel_eur=94, transport_eur=150)
    verifier_prix(124.0, devis).ok   # prix rapporté par l'agent H inscription

Voir docs/QUOTE.md.
"""

from urllib.parse import urlparse

from runai.quote.cost import resolve_options, weekend_cost
from runai.quote.klikego import KlikegoError, fetch_klikego_quote, fetch_klikego_quotes
from runai.quote.models import (
    CoutWeekend,
    Devis,
    LigneCout,
    OptionPayante,
    Palier,
    VerificationDevis,
    devis_answer_schema,
)
from runai.quote.njuko import (
    NjukoError,
    fetch_njuko_quote,
    fetch_njuko_quotes,
    slug_from_url,
)
from runai.quote.verify import total_attendu, verifier_devis, verifier_prix


def fetch_quote(url: str, epreuve: str | None = None, **kw) -> Devis:
    """Aiguille vers Njuko ou Klikego selon l'URL (un slug seul est traité comme Njuko)."""
    host = urlparse(url).netloc if "://" in url else ""
    if host.endswith("klikego.com"):
        return fetch_klikego_quote(url, epreuve, **kw)
    if not host or "njuko" in host:
        return fetch_njuko_quote(url, epreuve, **kw)
    raise ValueError(f"plateforme non prise en charge : {host}")


__all__ = [
    "CoutWeekend",
    "Devis",
    "KlikegoError",
    "LigneCout",
    "NjukoError",
    "OptionPayante",
    "Palier",
    "VerificationDevis",
    "devis_answer_schema",
    "fetch_klikego_quote",
    "fetch_klikego_quotes",
    "fetch_njuko_quote",
    "fetch_njuko_quotes",
    "fetch_quote",
    "resolve_options",
    "slug_from_url",
    "total_attendu",
    "verifier_devis",
    "verifier_prix",
    "weekend_cost",
]
