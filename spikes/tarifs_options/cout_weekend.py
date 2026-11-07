"""Coût total du week-end (inscription + options choisies + hôtel + transport) pour 3 courses.

    python spikes/tarifs_options/cout_weekend.py

Chaque ligne porte sa source : « mesure » (lu sur la plateforme le 07/11/2026) ou « estime »
(Linkup sourcedAnswer, prix moyens indicatifs, pas un devis daté). Départ Paris, 1 coureur, 1 nuit.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ligne:
    poste: str
    eur: float
    source: str  # "mesure" ou "estime"
    note: str = ""


@dataclass
class Weekend:
    course: str
    plateforme: str
    lignes: list[Ligne] = field(default_factory=list)

    def total(self, source: str | None = None) -> float:
        return round(sum(x.eur for x in self.lignes if source in (None, x.source)), 2)


COURSES = [
    Weekend(
        "Wizz Air Milano Marathon (04/04/2027)",
        "njuko",
        [
            Ligne(
                "inscription, palier actuel (jusqu'au 31/12/2026)",
                114,
                "mesure",
                "palier suivant 124 € puis 131 €",
            ),
            Ligne(
                "frais de service",
                0,
                "mesure",
                "5 € déjà inclus dans le tarif (texte de la carte)",
            ),
            Ligne("assurance annulation", 10, "mesure", "étape Services, optionnelle"),
            Ligne("t-shirt", 25, "mesure", "t-shirt blanc, étape Services, optionnel"),
            Ligne(
                "pass tourisme sportif",
                5,
                "mesure",
                "étape Participation requirements ; obligatoire ? à vérifier",
            ),
            Ligne(
                "hôtel ibis Milano, 1 nuit", 94, "estime", "moyenne ibis Milan (Linkup)"
            ),
            Ligne(
                "train Paris-Milan A/R", 150, "estime", "≈75 € l'aller à J-90 (Linkup)"
            ),
        ],
    ),
    Weekend(
        "Marathon Royan U Côte de Beauté (23/05/2027)",
        "klikego",
        [
            Ligne(
                "inscription, tarif actuel",
                65,
                "mesure",
                "70 € en dernière minute (date non affichée)",
            ),
            Ligne("frais de gestion Internet", 3, "mesure", "ajoutés au paiement"),
            Ligne("assurance annulation", 8, "mesure", "description de l'événement"),
            Ligne(
                "t-shirt technique (précommande)",
                12,
                "mesure",
                "description de l'événement",
            ),
            Ligne(
                "hôtel à Royan, 1 nuit",
                63,
                "estime",
                "source Linkup faible (pas un ibis)",
            ),
            Ligne(
                "train Paris-Royan A/R",
                180,
                "estime",
                "≈90 € l'aller (Linkup/Trainline)",
            ),
        ],
    ),
    Weekend(
        "10 km de Hyères (21/03/2027)",
        "njuko",
        [
            Ligne(
                "inscription, tarif unique",
                22,
                "mesure",
                "592 places restantes ; semi complet",
            ),
            Ligne(
                "frais de service",
                0,
                "mesure",
                "panier à 22 € lors du test H du 7/11 (BRAINSTORM)",
            ),
            Ligne("hôtel ibis budget Hyères, 1 nuit", 55, "estime", "53-60 € (Linkup)"),
            Ligne(
                "train Paris-Toulon A/R",
                200,
                "estime",
                "≈100 € l'aller ; Toulon-Hyères non chiffré",
            ),
        ],
    ),
]


def main() -> None:
    for w in COURSES:
        print(f"\n## {w.course} [{w.plateforme}]")
        for x in w.lignes:
            print(f"  {x.poste:<48} {x.eur:>7.2f} €  ({x.source}) {x.note}")
        print(
            f"  {'TOTAL':<48} {w.total():>7.2f} €  dont mesuré {w.total('mesure'):.2f} €, estimé {w.total('estime'):.2f} €"
        )
    print(
        "\n| Course | Inscription + options (mesuré) | Hôtel + transport (estimé) | Total |"
    )
    print("| --- | ---: | ---: | ---: |")
    for w in sorted(COURSES, key=Weekend.total):
        print(
            f"| {w.course} | {w.total('mesure'):.0f} € | {w.total('estime'):.0f} € | {w.total():.0f} € |"
        )


if __name__ == "__main__":
    main()
