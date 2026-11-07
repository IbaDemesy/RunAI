"""Devis njuko SANS session H : lecture de l'API front publique (GET uniquement).

    python spikes/tarifs_options/lecture_njuko.py wizz-air-milano-marathon-20271776152378557 [filtre_epreuve]

Ce sont les mêmes appels que la page publique fait au chargement (edition/url, prices-for-competition,
competition/remaining, fields). Aucun panier n'est créé par ce script, rien n'est soumis.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from devis_schema import Devis, OptionPayante, Palier, verifier_devis

API = "https://front-api.njuko.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (RunAI spike lecture seule)",
    "Accept": "application/json",
}
CATEGORIES = [
    ("assurance_annulation", r"assurance|annulation|insurance"),
    ("t_shirt", r"t-shirt|tee-shirt|maillot"),
    ("repas", r"repas|pasta|party|dîner|buffet"),
    ("navette", r"navette|bus|shuttle"),
    ("photos", r"photo"),
    ("don", r"\bdon\b|charit|solidaire"),
    ("medaille", r"médaille|gravure|medal"),
    ("pass_participation", r"tourisme sportif|pass|licence"),
    (
        "merchandising",
        r"casquette|sweat|veste|chaussette|sac|gourde|mug|porte-clés|tour de cou|manchette|bag|magnet|gobelet|peluche|tapis|dossard",
    ),
]


def _call(path: str, post: bool = False):
    data = b"{}" if post else None
    req = urllib.request.Request(
        API + path, data=data, headers={**HEADERS, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _tr(x):
    if isinstance(x, list) and x and isinstance(x[0], dict):
        for loc in ("fr_FR", "en_GB"):
            for i in x:
                if i.get("locale") == loc:
                    return i.get("translation")
        return x[0].get("translation")
    return x


def _txt(s) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _categorie(nom: str) -> str:
    for cat, pat in CATEGORIES:
        if re.search(pat, nom, re.IGNORECASE):
            return cat
    return "autre"


def _options(edition_id: str) -> list[OptionPayante]:
    opts: list[OptionPayante] = []

    def walk(node, form):
        for f in node.get("fields") or []:
            if not isinstance(f, dict):
                continue
            label = f.get("label")
            label = _txt(label if isinstance(label, str) else _tr(label))
            vals = (f.get("data") or {}).get("values") or []
            prix = [
                v.get("price") for v in vals if isinstance(v, dict) and v.get("price")
            ]
            p = f.get("price") or (min(prix) if prix else None)
            if p:
                req = bool((f.get("validateOptionsFormGroup") or {}).get("required"))
                opts.append(
                    OptionPayante(
                        nom=label[:120],
                        categorie=_categorie(label),
                        prix_eur=float(p),
                        obligatoire=req,
                        etape=form,
                    )
                )
            walk(f, form)

    for form in _call("fields/" + edition_id):
        name = form.get("name")
        walk(form, name if isinstance(name, str) else _tr(name))
    return opts


def devis(slug: str, filtre: str | None = None) -> list[Devis]:
    e = _call("edition/url/" + slug)
    course = _tr(e.get("name"))
    options = _options(e["_id"])
    now = datetime.now(UTC).isoformat()
    out = []
    for c in e.get("competitions", []):
        nom = _tr(c.get("name"))
        if filtre and filtre.lower() not in (nom or "").lower():
            continue
        paliers = sorted(
            _call("prices-for-competition/" + c["_id"]),
            key=lambda p: p.get("end") or "9999",
        )
        paliers = [
            p
            for p in paliers
            if p.get("enabled")
            and not p.get("isGroupPrice")
            and (p.get("end") or "9999") > now
        ]
        remaining = _call("competition/remaining/" + c["_id"], post=True).get(
            "remaining"
        )
        desc = _txt(_tr(c.get("description")) if c.get("description") else "")
        m = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:euros?|€)\s*de frais de service",
            desc,
            re.IGNORECASE,
        )
        frais = float(m.group(1).replace(",", ".")) if m else None
        alertes = []
        if not e.get("showPriceEndDate"):
            alertes.append(
                "date de fin de palier masquée sur la page publique (visible seulement via l'API)"
            )
        if frais is None:
            alertes.append(
                "frais de service non trouvés dans le texte : à confirmer au panier"
            )
        if not paliers:
            continue
        mk = lambda p: Palier(
            prix_eur=float(p["value"]), date_fin=(p.get("end") or "")[:10] or None
        )
        d = Devis(
            plateforme="njuko",
            course=course,
            epreuve=nom,
            date_epreuve=(c.get("startDate") or "")[:10] or None,
            url=f"https://in.njuko.com/{slug}",
            palier_actuel=mk(paliers[0]),
            paliers_suivants=[mk(p) for p in paliers[1:]],
            frais_service_eur=frais,
            frais_inclus_dans_prix=True if frais is not None else None,
            options=options,
            total_minimal_eur=float(paliers[0]["value"])
            + sum(o.prix_eur or 0 for o in options if o.obligatoire),
            complet=remaining == 0,
            etape_arret="page_course",
            raison_arret="lecture API publique, aucun parcours d'inscription",
            rien_soumis=True,
            avertissements=alertes,
        )
        out.append(d)
    return out


if __name__ == "__main__":
    for d in devis(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None):
        print(d.model_dump_json(indent=1, exclude={"options"}))
        print(
            f"  options payantes : {len(d.options)} ; ex. {[(o.nom[:40], o.prix_eur) for o in d.options[:4]]}"
        )
        for a in verifier_devis(d):
            print("  ALERTE :", a)
