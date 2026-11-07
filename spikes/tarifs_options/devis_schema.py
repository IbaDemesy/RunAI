"""answer_format de l'agent H « devis » (Pydantic -> JSON Schema).

Utilisation : client.run_session(..., answer_schema=Devis). Le schéma reste permissif
(champs optionnels) pour éviter les échecs `answer_validation` ; la cohérence du total
est vérifiée après coup par `verifier_devis`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Plateforme = Literal["njuko", "klikego", "autre"]
CategorieOption = Literal[
    "t_shirt",
    "repas",
    "assurance_annulation",
    "navette",
    "photos",
    "don",
    "medaille",
    "pass_participation",
    "merchandising",
    "autre",
]
EtapeArret = Literal[
    "page_course",
    "fiche_epreuve",
    "choix_epreuve",
    "identification_compte",
    "formulaire_participant",
    "cases_consentement",
    "options",
    "assurance",
    "panier",
    "choix_paiement",
    "bloque",
]


class Palier(BaseModel):
    prix_eur: float = Field(
        description="Prix de l'inscription pour ce palier, en euros."
    )
    date_fin: str | None = Field(
        default=None,
        description="Date de fin du palier (AAAA-MM-JJ) si elle est affichée, sinon null. Ne jamais deviner.",
    )
    libelle: str | None = Field(
        default=None, description="Texte affiché, ex. 'Inscriptions dernière minute'."
    )


class OptionPayante(BaseModel):
    nom: str = Field(description="Libellé exact de l'option sur la page.")
    categorie: CategorieOption
    prix_eur: float | None = Field(
        default=None, description="Prix en euros, null si non affiché."
    )
    obligatoire: bool = Field(
        description="true seulement si la page impose l'option pour continuer."
    )
    etape: str | None = Field(
        default=None, description="Étape du parcours où l'option apparaît."
    )


class Devis(BaseModel):
    plateforme: Plateforme
    course: str
    epreuve: str = Field(
        description="Nom exact de l'épreuve (ex. '10 km', 'Marathon')."
    )
    date_epreuve: str | None = Field(default=None, description="AAAA-MM-JJ.")
    url: str = Field(description="URL de la dernière page lue.")
    palier_actuel: Palier
    paliers_suivants: list[Palier] = Field(
        default_factory=list, description="Paliers futurs visibles, sinon []."
    )
    frais_service_eur: float | None = Field(
        default=None,
        description="Frais de service/gestion Internet affichés, null si non affichés.",
    )
    frais_inclus_dans_prix: bool | None = Field(
        default=None,
        description="true si la page dit que les frais sont compris dans le prix affiché.",
    )
    options: list[OptionPayante] = Field(default_factory=list)
    total_minimal_eur: float = Field(
        description="Prix du palier + frais (s'ils ne sont pas inclus) + options obligatoires uniquement."
    )
    complet: bool = Field(
        default=False,
        description="true si l'épreuve est affichée complète / liste d'attente.",
    )
    etape_arret: EtapeArret
    raison_arret: str = Field(
        description="Pourquoi l'agent s'est arrêté (règle, compte exigé, case santé, paiement...)."
    )
    rien_soumis: bool = Field(
        description="true si aucun formulaire n'a été soumis et aucun compte créé."
    )
    avertissements: list[str] = Field(
        default_factory=list,
        description="Incohérences ou doutes (prix différents, date de fin absente...).",
    )


def total_attendu(d: Devis) -> float:
    frais = (
        0.0
        if d.frais_inclus_dans_prix or d.frais_service_eur is None
        else d.frais_service_eur
    )
    obligatoires = sum(o.prix_eur or 0.0 for o in d.options if o.obligatoire)
    return round(d.palier_actuel.prix_eur + frais + obligatoires, 2)


def verifier_devis(d: Devis) -> list[str]:
    """Contrôles déterministes côté RunAI après la réponse de l'agent."""
    alertes: list[str] = []
    attendu = total_attendu(d)
    if abs(attendu - d.total_minimal_eur) > 0.01:
        alertes.append(
            f"total_minimal_eur={d.total_minimal_eur} mais recalcul={attendu}"
        )
    if not d.rien_soumis:
        alertes.append(
            "l'agent déclare avoir soumis quelque chose : à vérifier dans le replay H"
        )
    if d.palier_actuel.date_fin is None:
        alertes.append(
            "date de fin du palier non affichée : prix susceptible d'augmenter sans préavis"
        )
    if any(o.prix_eur is None for o in d.options):
        alertes.append("au moins une option sans prix affiché")
    return alertes


if __name__ == "__main__":
    out = Path(__file__).with_name("devis_answer_format.json")
    out.write_text(
        json.dumps(Devis.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
    print(f"schéma écrit : {out.name} ({len(out.read_text())} octets)")
