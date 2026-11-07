"""Modèles du devis d'inscription et du coût du week-end.

`Devis` sert à la fois pour la lecture directe de la plateforme (`source="api"`) et comme
`answer_schema` d'un agent H « devis » (`source="agent_h"`, voir `devis_answer_schema()`).
Valeurs d'énumération courtes : les agents H recopient mal les longues valeurs Literal.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

Plateforme = Literal["njuko", "klikego", "autre"]
SourceDevis = Literal["api", "agent_h", "manuel"]
SourceLigne = Literal["mesure", "agent", "estime"]
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
    date_fin: date | None = Field(
        default=None,
        description="Dernier jour du palier (AAAA-MM-JJ, heure locale de la course) s'il est connu, sinon null. Ne jamais deviner.",
    )
    libelle: str | None = Field(
        default=None, description="Texte affiché, ex. 'Inscriptions dernière minute'."
    )


class OptionPayante(BaseModel):
    id: str | None = Field(
        default=None, description="Identifiant plateforme, null si inconnu."
    )
    nom: str = Field(description="Libellé exact de l'option sur la page.")
    categorie: CategorieOption = "autre"
    prix_eur: float | None = Field(
        default=None, description="Prix en euros, null si non affiché."
    )
    obligatoire: bool = Field(
        default=False,
        description="true seulement si la page impose l'option pour continuer.",
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
    date_epreuve: date | None = Field(default=None, description="AAAA-MM-JJ.")
    url: str = Field(description="URL de la page d'inscription lue.")
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
        description="true si la page dit que les frais sont compris dans le prix affiché, null si inconnu.",
    )
    options: list[OptionPayante] = Field(default_factory=list)
    total_minimal_eur: float = Field(
        description="Prix du palier + frais (s'ils ne sont pas inclus) + options obligatoires uniquement."
    )
    complet: bool = Field(
        default=False,
        description="true si l'épreuve est affichée complète / liste d'attente.",
    )
    places_restantes: int | None = Field(
        default=None, description="Places restantes si affichées."
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
    source: SourceDevis = "agent_h"
    releve_le: datetime | None = None


class LigneCout(BaseModel):
    poste: str
    eur: float
    source: SourceLigne
    note: str = ""


class CoutWeekend(BaseModel):
    course: str
    epreuve: str
    lignes: list[LigneCout] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)
    releve_le: datetime | None = None

    @computed_field
    @property
    def total_eur(self) -> float:
        return round(sum(x.eur for x in self.lignes), 2)

    @computed_field
    @property
    def total_par_source(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for x in self.lignes:
            out[x.source] = round(out.get(x.source, 0.0) + x.eur, 2)
        return out


class VerificationDevis(BaseModel):
    """Résultat d'un contrôle : `ecarts` bloquants (prix faux, soumission), `avertissements` informatifs."""

    ecarts: list[str] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)
    attendu_eur: float | None = None

    @computed_field
    @property
    def ok(self) -> bool:
        return not self.ecarts


def devis_answer_schema() -> dict[str, Any]:
    """JSON Schema de `Devis` à passer en `answer_schema` à un agent H « devis »."""
    return Devis.model_json_schema()
