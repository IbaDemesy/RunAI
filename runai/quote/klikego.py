"""Devis Klikego en lecture seule : page événement publique + fiche épreuve (`/v8/evenement/epreuve.jsp`).

GET uniquement sur des pages autorisées par robots.txt ; on ne va jamais jusqu'à « S'inscrire »
(création de compte, interdite aux robots par les CGU). Les options sont dans le texte libre de
la description : extraction par mots-clés, indicative.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from runai.quote._common import eur, html_to_text, new_client, norm
from runai.quote.models import Devis, OptionPayante, Palier
from runai.quote.verify import total_attendu

BASE = "https://www.klikego.com"


def is_klikego_url(url: str) -> bool:
    """Vrai seulement pour une URL https de klikego.com (ou d'un sous-domaine)."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (
        host == "klikego.com" or host.endswith(".klikego.com")
    )


EUR = r"(\d+(?:[.,]\d+)?)\s*€"
_MOTS_OPTIONS = [
    ("assurance_annulation", r"assurance annulation|garantie annulation"),
    ("t_shirt", r"t-shirt|tee-shirt"),
    ("repas", r"repas|pasta"),
    ("navette", r"navette"),
    ("photos", r"photos?\b"),
    ("don", r"\bdons?\b"),
]


class KlikegoError(RuntimeError):
    pass


def parse_event(
    html: str,
) -> tuple[str, str, list[tuple[str, str]], list[OptionPayante]]:
    """Page événement -> (id événement, nom de la course, [(heat, nom épreuve)], options)."""
    ev = re.search(r"evenement/epreuve\.jsp\?embedded=1&(?:amp;)?e=([\d-]+)", html)
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    if not ev or not title:
        raise KlikegoError("page événement Klikego non reconnue")
    course = html_to_text(title.group(1)).split(" | ")[0]
    heats = re.findall(r"heatDetails\('(\d+)'\)", html)
    noms = [
        html_to_text(n)
        for n in re.findall(r'<h3 class="flex-1[^"]*">([^<]+)</h3>', html)
    ]
    desc = html_to_text(html)
    options = []
    for cat, pat in _MOTS_OPTIONS:
        m = re.search(pat, desc, re.IGNORECASE)
        if not m:
            continue
        fen = desc[m.start() : m.start() + 260]
        p = re.search(EUR, fen)
        options.append(
            OptionPayante(
                nom=fen[:80].strip(),
                categorie=cat,
                prix_eur=eur(p.group(1)) if p else None,
                etape="formulaire (après création du compte)",
            )
        )
    return ev.group(1), course, list(zip(heats, noms, strict=False)), options


def parse_fiche(
    html: str,
    *,
    url: str,
    course: str,
    epreuve: str,
    options: list[OptionPayante],
    now: datetime | None = None,
) -> Devis | None:
    """Fiche épreuve -> `Devis` (None si aucun tarif affiché)."""
    fiche = html_to_text(html)
    tarifs = re.findall(
        r"(Droits? d'inscription|Tarif[^:]{0,40}|Inscriptions dernière minute)\s*:\s*"
        + EUR,
        fiche,
    )
    if not tarifs:
        return None
    frais = re.search(EUR + r" de frais de gestion", fiche)
    actuel = (
        [t for t in tarifs if "Non-Licenci" in t[0]]
        or [t for t in tarifs if "dernière minute" not in t[0]]
        or tarifs
    )[0]
    fr = eur(frais.group(1)) if frais else None
    alertes = []
    if any("dernière minute" in t[0] for t in tarifs):
        alertes.append("tarif dernière minute affiché sans date de bascule")
    if fr is None:
        alertes.append("frais de gestion non affichés sur la fiche")
    complet = "S'inscrire" not in fiche
    d = Devis(
        plateforme="klikego",
        course=course,
        epreuve=epreuve,
        url=url,
        palier_actuel=Palier(prix_eur=eur(actuel[1]), libelle=actuel[0].strip()),
        paliers_suivants=[
            Palier(prix_eur=eur(p), libelle=lib.strip())
            for lib, p in tarifs
            if (lib, p) != actuel
        ],
        frais_service_eur=fr,
        frais_inclus_dans_prix=False if fr is not None else None,
        options=options,
        total_minimal_eur=0,
        complet=complet,
        etape_arret="fiche_epreuve",
        raison_arret="lecture de la fiche épreuve publique ; l'étape suivante crée un compte Klikego",
        rien_soumis=True,
        avertissements=alertes,
        source="api",
        releve_le=now or datetime.now(UTC),
    )
    d.total_minimal_eur = total_attendu(d)
    return d


def fetch_klikego_quotes(
    url: str,
    epreuve: str | None = None,
    *,
    limit: int | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> list[Devis]:
    """Devis des épreuves d'un événement Klikego (1 GET + 1 GET par épreuve lue, `limit` pour borner)."""
    if not is_klikego_url(url):
        raise KlikegoError(f"URL hors klikego.com : {url!r}")
    own = client is None
    client = client or new_client()
    try:
        r = client.get(url, follow_redirects=False)
        r.raise_for_status()
        ev, course, heats, options = parse_event(r.text)
        out: list[Devis] = []
        for heat, nom in heats:
            if epreuve and norm(epreuve) not in norm(nom):
                continue
            if limit is not None and len(out) >= limit:
                break
            f = client.get(
                f"{BASE}/v8/evenement/epreuve.jsp",
                params={"embedded": 1, "e": ev, "heat": heat},
                follow_redirects=False,
            )
            f.raise_for_status()
            d = parse_fiche(
                f.text, url=url, course=course, epreuve=nom, options=options, now=now
            )
            if d:
                out.append(d)
        return out
    finally:
        if own:
            client.close()


def fetch_klikego_quote(url: str, epreuve: str | None = None, **kw) -> Devis:
    """Premier devis Klikego correspondant à `epreuve` (2 requêtes). Lève `KlikegoError` si rien."""
    found = fetch_klikego_quotes(url, epreuve, limit=1, **kw)
    if not found:
        raise KlikegoError(f"aucune épreuve avec tarif ne correspond à {epreuve!r}")
    return found[0]
