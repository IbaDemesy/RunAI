"""Devis Njuko sans navigateur : API front publique `front-api.njuko.com`, lecture seule.

Mêmes appels que la page publique au chargement : `edition/url/{slug}` (épreuves),
`prices-for-competition/{id}` (paliers datés), `competition/remaining/{id}` (places, POST sans corps
utile, aucune création de panier) et `fields/{edition}` (options payantes du formulaire).
Rien n'est soumis, aucun compte ni panier n'est créé.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from runai.quote._common import categorie, html_to_text, new_client, norm
from runai.quote.models import Devis, OptionPayante, Palier
from runai.quote.verify import total_attendu

API = "https://front-api.njuko.com/"
GROUP_FORMS = {"GROUP", "GROUP_LEADER"}
_FRAIS = [
    r"(\d+(?:[.,]\d+)?)\s*(?:euros?|€)\s*de frais de service",
    r"frais de service[^.()]{0,60}\(\s*(\d+(?:[.,]\d+)?)\s*(?:euros?|€)\s*\)",
    r"service fees?[^.()]{0,60}\(\s*(?:€|eur)?\s*(\d+(?:[.,]\d+)?)",
]
# Njuko renvoie parfois des noms de fuseau Windows.
_WINDOWS_TZ = {
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "GMT Standard Time": "Europe/London",
    "E. Europe Standard Time": "Europe/Bucharest",
}
_INCLUS = re.compile(r"inclus|compris|included", re.IGNORECASE)


class NjukoError(RuntimeError):
    pass


def slug_from_url(url_or_slug: str) -> str:
    """`https://in.njuko.com/<slug>/...` ou `<slug>` -> `<slug>`."""
    s = url_or_slug.strip()
    if "://" in s:
        s = urlparse(s).path
    slug = s.strip("/").split("/")[0].split("?")[0]
    if not slug:
        raise NjukoError(f"slug Njuko introuvable dans {url_or_slug!r}")
    return slug


def _tr(x: Any, langs: tuple[str, ...] = ("fr_FR", "en_GB")) -> str:
    if isinstance(x, list) and x and isinstance(x[0], dict):
        for loc in langs:
            for i in x:
                if i.get("locale") == loc:
                    return i.get("translation") or ""
        return x[0].get("translation") or ""
    return x if isinstance(x, str) else ""


def _all_tr(x: Any) -> list[str]:
    if isinstance(x, list):
        return [i.get("translation") or "" for i in x if isinstance(i, dict)]
    return [x] if isinstance(x, str) else []


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(_WINDOWS_TZ.get(name or "", name or "Europe/Paris"))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class _Api:
    def __init__(self, client: httpx.Client):
        self.client = client

    def get(self, path: str) -> Any:
        r = self.client.get(API + path, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    def post(self, path: str) -> Any:
        r = self.client.post(
            API + path, json={}, headers={"Accept": "application/json"}
        )
        r.raise_for_status()
        return r.json()


def _options(forms: list[dict], competition_id: str) -> list[OptionPayante]:
    opts: list[OptionPayante] = []

    def walk(node: dict, etape: str) -> None:
        for f in node.get("fields") or []:
            if not isinstance(f, dict):
                continue
            group = f.get("validateOptionsFormGroup") or {}
            if group.get("visible") is False or group.get("organiserOnly"):
                walk(f, etape)
                continue
            vals = [
                v
                for v in (f.get("data") or {}).get("values") or []
                if isinstance(v, dict)
                and v.get("price")
                and v.get("visible", True) is not False
                and (
                    not v.get("displayOnCompetitions")
                    or competition_id in v["displayOnCompetitions"]
                )
            ]
            prix = f.get("price") or (min(v["price"] for v in vals) if vals else None)
            if prix:
                nom = html_to_text(_tr(f.get("label")))[:160]
                opts.append(
                    OptionPayante(
                        id=f.get("_id"),
                        nom=nom,
                        categorie=categorie(nom),
                        prix_eur=float(prix),
                        obligatoire=bool(group.get("required")),
                        etape=etape,
                    )
                )
            walk(f, etape)

    for form in forms:
        if form.get("type") in GROUP_FORMS:
            continue
        walk(form, _tr(form.get("name"), ("fr_FR", "en_GB")) or None)
    return opts


def _frais(texts: list[str]) -> tuple[float | None, bool | None]:
    for t in texts:
        for pat in _FRAIS:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                fen = t[max(0, m.start() - 80) : m.end() + 80]
                return float(m.group(1).replace(",", ".")), (
                    True if _INCLUS.search(fen) else None
                )
    return None, None


def _texts(node: Any) -> list[str]:
    """Tous les textes de description (HTML -> texte) d'un arbre JSON Njuko."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("description", "html"):
                out += [html_to_text(t) for t in _all_tr(v)]
            else:
                out += _texts(v)
    elif isinstance(node, list):
        for v in node:
            out += _texts(v)
    return out


def _match(competition: dict, epreuve: str) -> bool:
    q = norm(epreuve)
    return any(q in norm(n) for n in _all_tr(competition.get("name")))


def build_devis(
    slug: str,
    edition: dict,
    competition: dict,
    prices: list[dict],
    remaining: dict | None,
    forms: list[dict],
    *,
    now: datetime | None = None,
) -> Devis:
    """Construit le `Devis` à partir des réponses brutes de l'API (pur, testable sans réseau)."""
    now = now or datetime.now(UTC)
    tz = _tz(edition.get("timezone"))
    currency = edition.get("currency") or "EUR"
    alertes: list[str] = []
    if currency != "EUR":
        alertes.append(f"devise {currency} : montants non convertis")

    tiers = sorted(
        (
            p
            for p in prices
            if p.get("enabled")
            and not p.get("isGroupPrice")
            and not p.get("soldOutAt")
            and (_dt(p.get("end")) or datetime.max.replace(tzinfo=UTC)) > now
        ),
        key=lambda p: p.get("end") or "9999",
    )
    if not tiers:
        raise NjukoError(f"aucun palier ouvert pour {_tr(competition.get('name'))!r}")

    def palier(p: dict) -> Palier:
        end = _dt(p.get("end"))
        return Palier(
            prix_eur=float(p["value"]),
            date_fin=end.astimezone(tz).date() if end else None,
            libelle=_tr(p.get("name")) or None,
        )

    start = _dt(tiers[0].get("start"))
    if start and start > now:
        alertes.append(
            f"palier pas encore ouvert (ouverture le {start.astimezone(tz).date()})"
        )
    if not edition.get("showPriceEndDate"):
        alertes.append(
            "date de fin de palier masquée sur la page publique (lue via l'API)"
        )

    reg_start = _dt(competition.get("startDateRegistrations"))
    reg_end = _dt(competition.get("endDateRegistrations"))
    places = (remaining or {}).get("remaining")
    complet = places == 0 or bool(reg_end and reg_end <= now)
    if reg_start and reg_start > now:
        alertes.append(
            f"inscriptions ouvertes à partir du {reg_start.astimezone(tz).date()}"
        )
    if reg_end and reg_end <= now:
        alertes.append("inscriptions closes")

    frais, inclus = _frais(_texts(competition) + _texts(forms))
    if frais is None:
        alertes.append("frais de service non trouvés : à confirmer au panier")
    elif inclus is None:
        alertes.append(
            f"frais de service {frais:g} € trouvés dans le texte, inclusion dans le prix non précisée : à confirmer au panier"
        )

    start_date = _dt(competition.get("startDate"))
    d = Devis(
        plateforme="njuko",
        course=_tr(edition.get("name")),
        epreuve=_tr(competition.get("name")),
        date_epreuve=start_date.astimezone(tz).date() if start_date else None,
        url=f"https://in.njuko.com/{slug}",
        palier_actuel=palier(tiers[0]),
        paliers_suivants=[palier(p) for p in tiers[1:]],
        frais_service_eur=frais,
        frais_inclus_dans_prix=inclus,
        options=_options(forms, competition["_id"]),
        total_minimal_eur=0,
        complet=complet,
        places_restantes=places,
        etape_arret="page_course",
        raison_arret="lecture de l'API publique Njuko, aucun parcours d'inscription",
        rien_soumis=True,
        avertissements=alertes,
        source="api",
        releve_le=now,
    )
    d.total_minimal_eur = total_attendu(d)
    return d


def _competitions(edition: dict, epreuve: str | None) -> list[dict]:
    comps = sorted(
        (c for c in edition.get("competitions") or [] if not c.get("hideOnFront")),
        key=lambda c: c.get("position") or 0,
    )
    if epreuve:
        comps = [c for c in comps if _match(c, epreuve)]
    return comps


def fetch_njuko_quotes(
    url_or_slug: str,
    epreuve: str | None = None,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> list[Devis]:
    """Un `Devis` par épreuve visible (filtrée par `epreuve`, sous-chaîne insensible à la casse, toutes langues).

    Coût réseau : 2 + 2 × nb d'épreuves requêtes GET/POST, aucune authentification.
    """
    slug = slug_from_url(url_or_slug)
    own = client is None
    client = client or new_client()
    try:
        api = _Api(client)
        edition = api.get("edition/url/" + slug)
        comps = _competitions(edition, epreuve)
        if not comps:
            raise NjukoError(f"aucune épreuve ne correspond à {epreuve!r} sur {slug}")
        forms = api.get("fields/" + edition["_id"])
        return [
            build_devis(
                slug,
                edition,
                c,
                api.get("prices-for-competition/" + c["_id"]),
                api.post("competition/remaining/" + c["_id"]),
                forms,
                now=now,
            )
            for c in comps
        ]
    finally:
        if own:
            client.close()


def fetch_njuko_quote(
    url_or_slug: str,
    epreuve: str | None = None,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> Devis:
    """Devis Njuko d'une épreuve : paliers datés, palier courant, places, options payantes, frais.

    `url_or_slug` : `https://in.njuko.com/<slug>` ou `<slug>`. `epreuve` : filtre sur le nom de
    l'épreuve ; sans filtre, la première épreuve visible est prise (avertissement si plusieurs).
    4 requêtes HTTP. Lève `NjukoError` si aucune épreuve ou aucun palier ouvert, `httpx.HTTPError`
    si l'API ne répond pas.
    """
    slug = slug_from_url(url_or_slug)
    own = client is None
    client = client or new_client()
    try:
        api = _Api(client)
        edition = api.get("edition/url/" + slug)
        comps = _competitions(edition, epreuve)
        if not comps:
            raise NjukoError(f"aucune épreuve ne correspond à {epreuve!r} sur {slug}")
        c = comps[0]
        d = build_devis(
            slug,
            edition,
            c,
            api.get("prices-for-competition/" + c["_id"]),
            api.post("competition/remaining/" + c["_id"]),
            api.get("fields/" + edition["_id"]),
            now=now,
        )
        if len(comps) > 1:
            autres = "; ".join(_tr(x.get("name")) for x in comps[1:])
            d.avertissements.append(
                f"{len(comps)} épreuves correspondent, retenue : {d.epreuve!r} (autres : {autres})"
            )
        return d
    finally:
        if own:
            client.close()
