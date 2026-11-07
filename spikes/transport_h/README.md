# Spike axe 4 : transport via un agent H

Question : quel site de transport un agent H (`h/web-surfer-pro`) sait-il parcourir jusqu'à la page juste avant paiement, avec un passager fictif ?

3 runs H réels le 7 nov. 2026 (UTC), un à la fois, chaque session annulée en fin de run. Aucun paiement, aucune carte saisie.

## Résultats mesurés

| Site | Trajet demandé | Session H | Étapes | Durée | Captcha | Page finale | Prix |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TAP** (flytap.com) | Paris → Lisbonne A/R, sam. 6 / dim. 7 mars 2027 (Vodafone 10K) | `9d05f31a-c5d3-4905-b0b7-5f64771205d6` | 61 | 346 s | non | `booking.flytap.com/booking/payment`, bouton « Poursuivre vers le paiement » non cliqué | 179,35 € |
| **Trainline** | Paris → Milan, sam. 3 avr. 2027 (Milano Marathon) | `4b8a7ac0-2c19-4f4d-9b2a-c7a8d6461746` | 21 | 112 s | **oui** (slider « Slide right to secure your access ») | page de résultats bloquée | — |
| **Kombo** | Paris → Milan, sam. 3 avr. 2027, puis repli sur sam. 14 nov. 2026 | `e4556d53-7997-404e-b5ba-b322c3f4fb20` | 51 | 301 s | non | « Options aller », bouton « Aller au paiement » non cliqué | 94,00 € |

Détail des trajets (sorties `answer` des agents) :

- **TAP** : TP0440 ORY 06h40 → LIS 08h15 (sam. 6 mars), TP0441 LIS 18h10 → ORY 21h40 (dim. 7 mars), tarif Discount sans bagage en soute (97,47 € + 81,88 €). Mode invité (« Vous avez choisi de continuer sans vous connecter »), passager et coordonnées remplis. L'URL contient un PNR temporaire (`pnr=FK09361013`) dès la saisie passager, sans paiement.
- **Kombo** : Frecciarossa 9281, Paris Gare de Lyon 07h30 → Milano Centrale 14h07, direct, tarif Standard « Allegro ». Le 3 avril 2027 n'est **pas encore en vente** (Kombo affiche : inOui « prochaine mise en vente le 12 novembre 2026 », Frecciarossa « mise en vente plus tard »).
- **Trainline** : captcha dès la soumission de la recherche, l'agent s'est arrêté comme demandé.

Tokens (holo4-27b, entrée / dont cache / sortie) : TAP 1 616 223 / 1 191 200 / 20 167 ; Kombo 1 124 577 / 782 400 / 14 586 ; Trainline 333 859 / 194 400 / 4 993. Attente de slot : ~1 s à chaque run.

Fichiers bruts (réponse JSON, statut, tous les événements) : `results/*.json`. Vue H : `https://platform.hcompany.ai/agents/sessions/<id>`.

## Incidents relevés

- **Kombo ouvre Booking.com** : la case « hôtel » cochée par défaut ouvre une page de résultats Booking dans l'onglet courant au moment de la recherche. L'agent est revenu sur l'onglet Kombo sans interagir avec Booking. À corriger : demander dans le prompt de décocher cette case.
- **Kombo crée un compte implicite** : à la saisie passager, le site affiche « En continuant, vos infos sont sauvegardées dans un compte ». Pas de mot de passe ni de vérification e-mail, mais l'agent a continué avec `camille.martin@example.com`. Ça va contre la règle « aucun compte créé » ; à interdire dans le prompt (s'arrêter sur la page passager) si Kombo est retenu.
- **TAP** : la saisie de la date de naissance (liste déroulante d'années) a demandé plusieurs essais avant `select_option` ; le calendrier a un temps de chargement.

## CGU (lues le 7 nov. 2026)

- **Trainline** ([thetrainline.com/terms](https://www.thetrainline.com/terms), §12.2) : interdit « any engine, software, tool, agent or other device or mechanism (except … commercially available web browsers …) to navigate or search our booking service » et « robots, spiders, scripts or other automatic devices, to use our booking service ». Interdiction explicite des agents.
- **TAP** ([conditions générales](https://www.flytap.com/fr-fr/mentions-legales/conditions-generales)) : le client s'engage à « ne pas utiliser de logiciels manuels ou automatiques, d'appareils, de scripts, de robots … » pour du web scraping, crawling ou robot spider, et à « ne pas utiliser de scripts automatisés pour interagir avec ou collecter des informations sur le Site Internet ». Risque réel, formulé autour du scraping et des scripts.
- **Kombo** ([CGV du 3 juil. 2026](https://www.kombo.co/fr/cgv)) : usage « uniquement via l'interface graphique proposée », scraping interdit sans accord écrit ; « toute utilisation automatisée (scripts, robots…) … peut entraîner une suspension du Compte ». Risque réel, sanction = suspension.
- **Omio** : CGU non lues (HTTP 403 sur toutes les pages via curl).

Aucun des trois sites n'autorise explicitement un agent IA. Trainline est le plus explicite contre.

## Recommandation pour la démo

**TAP (vol)** : seul parcours complet jusqu'à la page de paiement, sans captcha ni compte, dates de mars 2027 en vente, horaires cohérents (arrivée samedi 08h15 pour le retrait des dossards, retour dimanche 18h10 après la course). Il colle à un scénario Lisbonne (Accor ibis Lisboa déjà testé). **Plan B train : Kombo**, à condition de décocher la case hôtel et de s'arrêter avant la page passager (compte implicite). Trainline est à abandonner (captcha + CGU).

Non mesuré : fiabilité sur plusieurs runs (1 run par site), comportement du captcha Trainline sur un autre run, disponibilité des trains Paris → Milan d'avril 2027 après le 12 nov.

## Relancer

```bash
.venv/bin/python spikes/transport_h/run_transport.py tap        # ou trainline, kombo, omio
.venv/bin/python spikes/transport_h/summarize.py                # résumé de results/*.json
```

Le script lit `HAI_API_KEY` (env ou `.env`), attend un slot H (max 10 min, contrôle toutes les 60 s), lance une session (80 étapes, 20 min max), écrit `results/<cible>_<horodatage>.json` et annule toujours la session à la fin. Une session consomme 1 des 3 slots de l'organisation.
