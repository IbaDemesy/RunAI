# Spike axe 3 — Hôtel Accor via un agent H

Prototype : à partir d'une course réelle 2027 (adresse de départ + dates), un agent H
(`h/web-surfer-pro`) cherche sur all.accor.com les hôtels proches du départ, compare 3-4 options
(distance affichée par Accor + prix), en choisit un, remplit le profil fictif **sans créer de compte**
et **s'arrête sur la page de paiement** (aucune carte saisie, bouton « Réserver » jamais cliqué).
Une correction « à moins de 10 min à pied du départ » est envoyée en cours de route via `send_message`.

## Ce qui est prouvé (3 runs H, 2026-11-07)

- Le parcours Accor complet (recherche → hôtel → chambre/tarif → extras → coordonnées → paiement)
  passe **3/3** sans compte, sans captcha, sans Cloudflare, sans popup bloquant.
- Arrêt fiable avant paiement 3/3 : page « Confirmez votre réservation », champs carte vides
  (seul « Nom du porteur » est pré-rempli `Martin` par Accor). Voir `results/run*/last_screenshot.png`.
- `answer_format` (Pydantic `HotelAnswer`) respecté 3/3 : hôtel, adresse, distance, prix,
  annulation, URL finale, description de capture, options comparées, blocages.
- Correction en cours de route : prise en compte **seulement si elle est formulée de façon impérative**.
  - run2 (correction douce) : l'agent la cite mais garde l'hôtel à 0,87 km (hors contrainte).
  - run3 (correction ferme + `pause()` avant `send_message`) : l'agent abandonne l'hôtel à 1,11 km,
    relance la recherche depuis « Arc de Triomphe » et choisit le Sofitel à 0,47 km.

## Course utilisée

Marathon de Paris 2027, dimanche 4 avril 2027, départ avenue des Champs-Élysées au pied de l'Arc de
Triomphe (trouvé via Linkup `sourcedAnswer`, sources ouest-france.fr / jds.fr). Nuit du 3 au 4 avril 2027,
1 adulte. Voir `race.json`.
Profil fictif : Camille Martin, camille.martin@example.com, +33 6 00 00 00 00, née le 12/05/1994,
1 rue de l'Exemple 75011 Paris.

## Relancer

```bash
# HAI_API_KEY dans l'environnement ; 1 run = 1 session H (quota vérifié avant, cancel() en finally)
.venv/bin/python spikes/hotel_h/run_hotel.py --run run4 --critere moins_cher \
  --correction-on-url "/booking/fr/accor/hotel/" --correction-ferme --pause-avant-correction
```

Options : `--critere compromis|moins_cher`, `--correction-after-s N` (déclenchement temporel, `<0` = pas
de correction), `--correction-on-url TXT` (déclenchement quand l'URL contient TXT), `--correction-ferme`,
`--pause-avant-correction`, `--max-time-s`, `--max-steps`. Sorties : `results/<run>/result.json`,
`events.json`, `events.log`, `last_screenshot.png`.

## Résultats MESURÉS

| | run1 | run2 | run3 |
|---|---|---|---|
| Session H | `102989c2-cf2c-44fa-9cae-aad53df884bd` | `434e52f6-9749-4d39-905a-6bc92674e6dd` | `ef4d6527-14dd-43f3-9d54-9f4a21332f77` |
| Quota avant (limit/actif/dispo) | 3/2/1 | 3/2/1 | 3/0/3 |
| Critère | compromis | moins cher | moins cher |
| Correction | douce, à t+103,9 s | douce, à t+127,5 s (URL hôtel) | ferme + pause, à t+134,8 s (URL hôtel) |
| Durée totale | 349,6 s | 330,8 s | 335,0 s |
| Étapes (API) | 61 | 59 | 62 |
| Événements / captures | 244 / 56 | 238 / 55 | 251 / 59 |
| Coût H (MetricsUpdate) | 0,288 USD | 0,270 USD | 0,293 USD |
| Hôtel choisi | Sofitel Paris Arc de Triomphe | Hotel Maison Hamelin (Handwritten Coll.) | Sofitel Paris Arc de Triomphe |
| Distance (affichée Accor) | 0,47 km | 0,87 km | 0,47 km |
| Prix total | 660,70 € | 418,45 € | 660,70 € |
| Annulation | gratuite jusqu'au 02/04/2027 18:00 | gratuite jusqu'au 02/04/2027 23:59 | gratuite jusqu'au 02/04/2027 18:00 |
| Étape atteinte | page `.../booking/fr/accor/payment?...` | idem | idem |
| Contrainte < 800 m respectée | oui (choix initial déjà conforme) | **non** | **oui, après changement d'hôtel** |
| Blocages | aucun | aucun | aucun |
| cancel() | ok | ok | ok |

Autres mesures :
- `pause()` → statut `paused` en 4,2 s ; 5 s après `send_message` le statut est repassé à `running`
  (le message relance la session).
- Run3 : correction envoyée à 134,8 s, prise en compte dans la réflexion suivante (horodatée 135,0 s) :
  « Le Hotel Maison Hamelin Paris est à 1.11 km — c'est trop loin. Je dois l'abandonner. »
- Run3 : l'agent avait d'abord cherché « Champs-Élysées » (distances calculées depuis un autre point :
  Hamelin à 1,11 km au lieu de 0,87 km). Après correction il a relancé la recherche sur
  « Arc de Triomphe, Place Charles de Gaulle ». **Imposer la destination dans le prompt.**
- Options vues (distance Accor depuis l'Arc de Triomphe) : Le Royal Monceau 0,44 km / 1 206 € ;
  Sofitel Arc de Triomphe 0,47 km / 596-627 € membre ; Maison Hamelin 0,87 km / 340-357 € ;
  Sofitel Baltimore Tour Eiffel 0,92 km / 460 € ; 2 Mercure Arc de Triomphe (0,25 et 0,51 km)
  **indisponibles** à ces dates.
- Frictions non bloquantes : liste « Nationalité » longue (erreurs de format `scroll_element`,
  résolu via `select_option`) ; Accor exige une adresse de facturation (run1 : l'agent en a inventé
  une fictive, ajoutée au profil ensuite) ; choix « tarif public » (sans adhésion fidélité) à faire
  explicitement ; nouvel onglet ouvert à chaque « Voir l'hôtel ».
- La boucle de flux voit `idle` en fin de tâche ; la session est ensuite annulée par `cancel()`.

## ESTIMÉ (non mesuré)

- Distance à pied : l'agent convertit la distance affichée par Accor (« de votre recherche »,
  probablement à vol d'oiseau) en minutes (~12 min/km). Non vérifié avec un calcul d'itinéraire.
- Durée en démo : ~5,5 min par run ici ; variable selon la charge H et les dates (non mesuré ailleurs).
- Taux de succès réel : 3/3 sur un seul couple course/dates, échantillon trop petit pour un taux.

## CGU Accor (lecture rapide)

- Conditions de vente (`all.accor.com/fr/booking/internet-sales-conditions.html`) et conditions
  légales (`all.accor.com/a/en/information/legal-conditions.html`) : pas de clause trouvée nommant
  robots / bots / IA ; interdiction d'extraction substantielle ou répétée du contenu (droit des bases
  de données).
- `robots.txt` : `Disallow: /booking/`, `/*/reservation/`, `/a/*/search.html` — vise les crawlers ;
  notre usage est un parcours unitaire piloté par l'utilisateur, la réservation finale reste humaine.
- Pas un avis juridique : à présenter comme « assistant qui prépare, l'humain réserve ».
