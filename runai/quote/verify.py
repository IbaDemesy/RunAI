"""Contrôles déterministes d'un devis ou d'un prix rapporté par un agent H, contre la source."""

from __future__ import annotations

from collections.abc import Iterable

from runai.quote._common import norm
from runai.quote.models import Devis, OptionPayante, VerificationDevis


def total_attendu(d: Devis) -> float:
    """Palier actuel + frais s'ils sont explicitement hors prix + options obligatoires."""
    frais = (
        d.frais_service_eur
        if d.frais_inclus_dans_prix is False and d.frais_service_eur
        else 0.0
    )
    obligatoires = sum(o.prix_eur or 0.0 for o in d.options if o.obligatoire)
    return round(d.palier_actuel.prix_eur + frais + obligatoires, 2)


def _find_option(
    o: OptionPayante, options: list[OptionPayante]
) -> OptionPayante | None:
    if o.id:
        for s in options:
            if s.id == o.id:
                return s
    q = norm(o.nom)
    exact = [s for s in options if norm(s.nom) == q]
    if exact:
        return exact[0]
    near = [s for s in options if q and (q in norm(s.nom) or norm(s.nom) in q)]
    return near[0] if len(near) == 1 else None


def _tier_hint(prix: float, source: Devis, tol: float) -> str:
    for p in source.paliers_suivants:
        if abs(p.prix_eur - prix) <= tol:
            fin = f" (fin {p.date_fin})" if p.date_fin else ""
            return f" ; correspond à un palier suivant{fin}"
    return ""


def verifier_devis(
    devis: Devis, source: Devis | None = None, *, tolerance_eur: float = 0.01
) -> VerificationDevis:
    """Contrôle un `Devis` (typiquement renvoyé par un agent H).

    Sans `source` : cohérence interne (total recalculé, `rien_soumis`, dates, prix manquants).
    Avec `source` (ex. `fetch_njuko_quote`) : palier actuel, frais, prix de chaque option et
    statut complet comparés à la plateforme.
    """
    v = VerificationDevis(attendu_eur=total_attendu(source or devis))
    attendu = total_attendu(devis)
    if abs(attendu - devis.total_minimal_eur) > tolerance_eur:
        v.ecarts.append(
            f"total_minimal_eur={devis.total_minimal_eur:g} mais recalcul={attendu:g}"
        )
    if not devis.rien_soumis:
        v.ecarts.append(
            "l'agent déclare avoir soumis quelque chose : vérifier dans le replay H"
        )
    if devis.palier_actuel.date_fin is None:
        v.avertissements.append(
            "date de fin du palier inconnue : prix susceptible d'augmenter sans préavis"
        )
    if any(o.prix_eur is None for o in devis.options):
        v.avertissements.append("au moins une option sans prix affiché")
    if devis.complet:
        v.avertissements.append("épreuve déclarée complète")
    if source is None:
        return v

    if norm(source.epreuve) not in norm(devis.epreuve) and norm(
        devis.epreuve
    ) not in norm(source.epreuve):
        v.avertissements.append(
            f"épreuve différente : agent {devis.epreuve!r}, source {source.epreuve!r}"
        )
    pa, ps = devis.palier_actuel.prix_eur, source.palier_actuel.prix_eur
    if abs(pa - ps) > tolerance_eur:
        v.ecarts.append(
            f"palier actuel : agent {pa:g} €, source {ps:g} €{_tier_hint(pa, source, tolerance_eur)}"
        )
    if source.frais_service_eur and devis.frais_service_eur is None:
        v.ecarts.append(
            f"frais non rapportés par l'agent : source {source.frais_service_eur:g} €"
        )
    elif (
        devis.frais_service_eur is not None
        and source.frais_service_eur is not None
        and abs(devis.frais_service_eur - source.frais_service_eur) > tolerance_eur
    ):
        v.ecarts.append(
            f"frais : agent {devis.frais_service_eur:g} €, source {source.frais_service_eur:g} €"
        )
    if (
        source.frais_service_eur
        and source.frais_inclus_dans_prix is not None
        and devis.frais_inclus_dans_prix is not None
        and devis.frais_inclus_dans_prix != source.frais_inclus_dans_prix
    ):
        v.ecarts.append(
            f"inclusion des frais : agent {devis.frais_inclus_dans_prix}, "
            f"source {source.frais_inclus_dans_prix}"
        )
    for o in devis.options:
        s = _find_option(o, source.options)
        if s is None:
            v.avertissements.append(f"option absente de la source : {o.nom}")
        elif (
            o.prix_eur is not None
            and s.prix_eur is not None
            and abs(o.prix_eur - s.prix_eur) > tolerance_eur
        ):
            v.ecarts.append(
                f"option {s.nom!r} : agent {o.prix_eur:g} €, source {s.prix_eur:g} €"
            )
    for s in source.options:
        if s.obligatoire and not any(_find_option(o, [s]) for o in devis.options):
            v.ecarts.append(f"option obligatoire non rapportée par l'agent : {s.nom}")
    if devis.complet != source.complet:
        v.ecarts.append(f"complet : agent {devis.complet}, source {source.complet}")
    return v


def verifier_prix(
    prix_eur: float,
    source: Devis,
    options_choisies: Iterable[str] = (),
    *,
    tolerance_eur: float = 0.01,
) -> VerificationDevis:
    """Contrôle un prix d'inscription rapporté par un agent (ex. `StepResult.price_eur` au panier).

    Attendu = palier actuel + frais hors prix + options obligatoires et `options_choisies`.
    Si l'inclusion des frais est inconnue, le prix avec ou sans frais est accepté (avertissement).
    """
    from runai.quote.cost import registration_lines

    lignes, alertes = registration_lines(source, options_choisies)
    attendu = round(sum(x.eur for x in lignes), 2)
    acceptes = [attendu]
    if source.frais_service_eur and source.frais_inclus_dans_prix is None:
        acceptes.append(round(attendu + source.frais_service_eur, 2))
    v = VerificationDevis(attendu_eur=attendu, avertissements=alertes)
    match = next((a for a in acceptes if abs(prix_eur - a) <= tolerance_eur), None)
    if match is None:
        v.ecarts.append(
            f"prix rapporté {prix_eur:g} €, attendu {' ou '.join(f'{a:g} €' for a in acceptes)}"
            + _tier_hint(
                prix_eur - (attendu - source.palier_actuel.prix_eur),
                source,
                tolerance_eur,
            )
        )
    elif match != attendu:
        v.avertissements.append(
            f"prix rapporté inclut les frais de service ({source.frais_service_eur:g} €)"
        )
    if source.complet:
        v.avertissements.append(
            "épreuve complète ou inscriptions closes selon la source"
        )
    return v
