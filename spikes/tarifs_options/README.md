# Spike C — tarifs, paliers et options (Njuko / Klikego)

Relevés du 07/11/2026, **sans session H**, en lecture seule (API publique Njuko, pages publiques Klikego, Linkup). Aucun formulaire soumis, aucun compte créé, aucun panier.

## Ce qui est prouvé

- **Njuko** : tout le devis se lit sans navigateur via `front-api.njuko.com` (`edition/url/{slug}`, `prices-for-competition/{id}` = paliers datés, `competition/remaining/{id}` = places, `fields/{edition}` = options du formulaire « Services », `workflow/active/{edition}/DESKTOP` = étapes).
  - Parcours : `selectCompetition` (prix du palier + texte des frais) → `registrationForm` (identité, *Participation requirements*, *Privacy*, **Services = options payantes**, *Insurance*) → `cart` → `selectPaymentMethod` (frais par moyen de paiement) → `doPayment`.
  - Les frais de service apparaissent en texte libre sous l’épreuve (« 5 euros de frais de service » inclus, Milan). L’endpoint `message/…` exige un `page` non trouvé : le script laisse `frais_service_eur=null` et un avertissement.
- **Klikego** : la page événement affiche « À partir de X € » ; la fiche épreuve (`/v8/evenement/epreuve.jsp?embedded=1&e=…&heat=…`) donne le droit d’inscription, le tarif non licencié / dernière minute et les **frais de gestion Internet**. Les options (assurance, t-shirt) sont dans la description de l’événement ; leur saisie se fait après « S’inscrire » → page *Inscription personnelle*, qui **demande un email et crée un compte** : c’est l’arrêt obligatoire.
- Le schéma `Devis` (Pydantic) + `verifier_devis()` permet de contrôler côté serveur le total et `rien_soumis` renvoyés par H.

## Résultats mesurés (07/11/2026)

| Course | Plateforme | Épreuve | Palier actuel | Frais | Options repérées | Statut |
| --- | --- | --- | ---: | --- | --- | --- |
| Wizz Air Milano Marathon (04/04/2027) | Njuko | Marathon (étrangers) | 114 € (jusqu’au 31/12/2026) → 124 € (28/02/2027) → 131 € (03/04/2027) | 5 € inclus (texte) | 25 options Services : assurance 10 €, t-shirt 25 €, t-shirt technique 30 €, sweat/veste 45 €, gravure 10 €… | 7 983 places |
| Semi de Hyères (21/03/2027) | Njuko | 10 km / semi | 22 € / 30 € | non affichés (panier 22 €) | aucune | 10 km : 592 places ; semi **complet** |
| Trail Urbain d’Orange | Njuko | 8 km / 13 km / marche | 11 € / 17 € / 12 € (fin 06/02/2027) | non affichés | aucune | ouvert |
| Marathon Royan U Côte de Beauté (23/05/2027) | Klikego | marathon / semi / 10 km | 65 € (70 € dernière minute) / 40 € / 23 € | +3 € / +2 € / +1,50 € | assurance annulation 8 €, t-shirt 12 € | ouvert |
| Marathon des Sables d’Olonne 2027 | Klikego | marathon / 10 km FFA / 10 km | 90 € / 18 € / 27 € | +2,50 € / +1,20 € / +1,70 € | — | marathon **complet** |

Grille générale Klikego (`/services/tarifs.jsp`) : 0,80 € (3–7,99 €) … 1,70 € (20–39,99 €), 2,20 € (40–79,99 €), 2,50 € (80–139,99 €) ; l’organisateur peut absorber ou répercuter la commission, d’où des frais différents sur les fiches.
Durée des scripts de lecture : Njuko 3,7 s (Hyères), Klikego 2,0 s (Royan, 1 épreuve). Détail brut : `mesures/releves_2026-11-07.json`.

## Coût du week-end (`cout_weekend.py`) — départ Paris, 1 nuit

| Course | Inscription + options (MESURÉ) | Hôtel + train A/R (ESTIMÉ, Linkup) | Total |
| --- | ---: | ---: | ---: |
| 10 km de Hyères | 22 € | 255 € | **277 €** |
| Marathon de Royan (+ assurance, t-shirt) | 88 € | 243 € | **331 €** |
| Marathon de Milan (+ assurance 10 €, t-shirt 25 €, « acceptation & assurance participation » 5 €) | 154 € | 244 € | **398 €** |

Hôtel/train = moyennes indicatives Linkup (`mesures/linkup_logistique.json`), pas des devis datés : à remplacer par la sortie des agents hôtel/transport.

## Agent H « devis » (prêt, **non lancé**)

- `devis_answer_format.json` : JSON Schema de `Devis` (course, épreuve, palier actuel + date de fin, paliers suivants, frais, options `[nom, prix, obligatoire]`, total minimal, url, `etape_arret`, `rien_soumis`).
- `skills/njuko-devis.md`, `skills/klikego-devis.md` : runbooks par plateforme (refus cookies, aucune case cochée, arrêt au panier / avant création de compte).
- `h_devis.py` : prompts + lanceur (dry-run par défaut ; `--run` vérifie le quota, attend 10 min max, `cancel()` en `finally`).

**ESTIMÉ** (aucune mesure H sur cet axe) : un devis Klikego ≈ 8–12 étapes, 1–2 min ; un devis Njuko ≈ 15–25 étapes, 2–5 min (il faut traverser `registrationForm` pour voir les Services). Base : 22 étapes = 1 min 56 (Booking, Linkup + H) et 40–64 étapes = 10–15 min (inscription complète), cf. `docs/`. Avec 3 slots libres : ~3 devis en parallèle par vague de ~5 min, soit 9–12 devis sur 15–20 min. Pendant la démo les 3 slots servent à la boucle inscription/hôtel/transport : **0 slot libre**, donc devis en lecture HTTP (2–4 s) ou pré-calculés ; H « devis » seulement en préparation.

## CGU à retenir

- **Klikego** (CGU PDF) : suppression de compte en cas d’usage de **robots**, de fausses inscriptions ou d’informations personnelles fausses ; commission conservée en cas de remboursement ; pas de droit de rétractation. `robots.txt` interdit panier/paiement/formulaires (non appelés ici). → jamais de compte avec données fictives, arrêt avant l’email.
- **Njuko** (`cgus/front/{edition}`) : définit « Njuko Options » et « Partner Options » (assurance, etc.) ; aucune clause robot/scraping trouvée dans ce texte (ce n’est pas une preuve d’absence ailleurs).

## Relancer

```bash
.venv/bin/python spikes/tarifs_options/lecture_njuko.py wizz-air-milano-marathon-20271776152378557 "non comp"
.venv/bin/python spikes/tarifs_options/lecture_klikego.py https://www.klikego.com/inscription/11eme-marathon-royan-u-cote-de-beaute-2027/running-course-a-pied/1446588740963-17 Marathon
.venv/bin/python spikes/tarifs_options/cout_weekend.py
.venv/bin/python spikes/tarifs_options/devis_schema.py          # régénère devis_answer_format.json
.venv/bin/python spikes/tarifs_options/h_devis.py njuko <url> "10 km"        # dry-run ; --run = vraie session H
```
