"""Coût total du week-end : inscription + frais + options choisies + hôtel + transport."""

from __future__ import annotations

from collections.abc import Iterable

from runai.quote._common import norm
from runai.quote.models import CoutWeekend, Devis, LigneCout, OptionPayante, SourceLigne


def resolve_options(devis: Devis, choix: Iterable[str]) -> list[OptionPayante]:
    """Options du devis désignées par id, nom exact ou sous-chaîne unique du nom (insensible à la casse).

    Lève `ValueError` si un choix est inconnu ou ambigu.
    """
    out: list[OptionPayante] = []
    for c in choix:
        q = norm(c)
        found = [o for o in devis.options if o.id == c or norm(o.nom) == q]
        if not found:
            found = [o for o in devis.options if q in norm(o.nom)]
        if len(found) != 1:
            noms = [o.nom for o in found] or [o.nom for o in devis.options]
            raise ValueError(
                f"option {c!r} {'ambiguë' if found else 'inconnue'} ; candidates : {noms}"
            )
        if found[0] not in out:
            out.append(found[0])
    return out


def registration_lines(
    devis: Devis, options_choisies: Iterable[str] = ()
) -> tuple[list[LigneCout], list[str]]:
    """Lignes inscription + frais (si non inclus) + options obligatoires et choisies."""
    src: SourceLigne = "mesure" if devis.source == "api" else "agent"
    p = devis.palier_actuel
    fin = f" (jusqu'au {p.date_fin:%d/%m/%Y})" if p.date_fin else ""
    suivants = ", ".join(f"{x.prix_eur:g} €" for x in devis.paliers_suivants)
    lignes = [
        LigneCout(
            poste=f"inscription {devis.epreuve}, palier actuel{fin}",
            eur=p.prix_eur,
            source=src,
            note=f"paliers suivants : {suivants}" if suivants else "",
        )
    ]
    alertes: list[str] = []
    if devis.frais_service_eur is not None:
        if devis.frais_inclus_dans_prix is False:
            lignes.append(
                LigneCout(
                    poste="frais de service", eur=devis.frais_service_eur, source=src
                )
            )
        elif devis.frais_inclus_dans_prix is None:
            alertes.append(
                f"frais de service {devis.frais_service_eur:g} € non comptés (inclusion dans le prix non confirmée)"
            )
    choisies = resolve_options(devis, options_choisies)
    for o in [o for o in devis.options if o.obligatoire] + [
        o for o in choisies if not o.obligatoire
    ]:
        if o.prix_eur is None:
            alertes.append(f"option sans prix affiché, non comptée : {o.nom}")
            continue
        lignes.append(
            LigneCout(
                poste=f"option : {o.nom}",
                eur=o.prix_eur,
                source=src,
                note="obligatoire" if o.obligatoire else (o.etape or ""),
            )
        )
    return lignes, alertes


def weekend_cost(
    devis: Devis,
    options_choisies: Iterable[str] = (),
    hotel_eur: float | None = None,
    transport_eur: float | None = None,
    *,
    hotel_source: SourceLigne = "estime",
    transport_source: SourceLigne = "estime",
    hotel_note: str = "",
    transport_note: str = "",
) -> CoutWeekend:
    """Détail ligne par ligne et total du week-end, chaque ligne avec sa source.

    `options_choisies` : ids ou noms d'options du devis (voir `resolve_options`) ; les options
    obligatoires sont toujours ajoutées. `hotel_eur` / `transport_eur` : montants totaux du séjour
    (ex. prix au point d'arrêt des agents H, `source="agent"`) ou estimation (`"estime"`) ;
    `None` = non chiffré (avertissement, total partiel).
    """
    lignes, alertes = registration_lines(devis, options_choisies)
    for poste, eur, source, note in (
        ("hôtel", hotel_eur, hotel_source, hotel_note),
        ("transport", transport_eur, transport_source, transport_note),
    ):
        if eur is None:
            alertes.append(f"{poste} non chiffré : total partiel")
        else:
            lignes.append(
                LigneCout(poste=poste, eur=float(eur), source=source, note=note)
            )
    if devis.complet:
        alertes.append("épreuve complète ou inscriptions closes")
    return CoutWeekend(
        course=devis.course,
        epreuve=devis.epreuve,
        lignes=lignes,
        avertissements=alertes,
        releve_le=devis.releve_le,
    )
