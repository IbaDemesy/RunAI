# Recherches des agents : synthèse et évaluation

> Synthèse des 16 agents du workflow d'exploration `runai-exploration-v1` (7 nov. 2026) : 9 explorateurs, une synthèse, une critique (« avocat du diable ») et 5 approfondissements. Les efforts sont ceux **annoncés par les agents, pas mesurés**. La colonne « Preuve ou raison » précise ce qui a été vérifié.

## En bref

- **Attente au portail : elle tient.** Une session H est restée 19,5 min en `awaiting_tool_results` sans client connecté, puis un `send_message` l'a relancée et elle s'est terminée en succès. C'est un seul essai, mais lancer les 3 sessions environ 12 min avant le passage devient crédible.
- **On fait** : 8 idées, environ 22 h en séquentiel. C'est trop pour une seule personne en 24 h : il faut répartir entre l'équipe et Devin.
- **En option** : 8 idées, environ 22,5 h, seulement si le cœur tient.
- **Coupé** : 6 idées, à cause des CGU, d'un captcha, du quota H ou du faible nombre de points.

La procédure de démo et de livrables qui en découle est dans [DEMO_ET_LIVRABLES.md](DEMO_ET_LIVRABLES.md).

## On fait

| Idée | Effort (h) | Critères jury | Preuve ou raison | Agents |
| --- | --- | --- | --- | --- |
| Inscription multi-plateforme jusqu'au paiement (Njuko, Klikego, site inconnu en mode générique) | 4 | Computer use, fiabilité | 1 run H réussi par plateforme le 7 nov. | inscription, synthèse |
| Séjour calé sur la logistique de la course : retrait du dossard, accès au départ, hôtel Accor près du vrai point d'accès | 3 | Originalité | Règlements lus ; CGU Accor sans clause anti-IA | voyage, dig-r1-1 |
| Linkup hybride : /search trouve la page officielle, puis l'agent H démarre dessus (search/fetch en secours) | 3 | Prix Linkup, fiabilité | Clé OK, 1 à 3 s, 0,006 $ par appel | devin-linkup-h |
| Portail « l'agent remplit, l'humain signe » sur chaque case santé, règlement, RGPD et avant paiement | 1,5 | UX et contrôle humain | Session H tenue ~20 min en attente, reprise OK (dig-r1-3) | dig-r1-1, devin-linkup-h |
| Voix comme télécommande : « stop » met en pause, une correction devient send_message | 3 | Prix Gladia | Docs Gladia et H ; latence non mesurée | gladia |
| Réponses typées, journal d'étapes, vérification croisée H et Linkup | 2,5 | Fiabilité | Docs H | devin-linkup-h |
| Banc de fiabilité : 15 runs (5 par plateforme), tableau des taux de réussite | 2 | Fiabilité (25 %) | 70 à 105 min théoriques sur 3 slots | veille, dig-r1-2 |
| Vidéo générée par script : Playwright, voix off, sous-titres Gladia, ffmpeg | 3 | Livrable obligatoire, prix Gladia | Non construit | session Devin de Mathieu |

## Option (si le cœur tient)

| Idée | Effort (h) | Critères jury | Preuve ou raison | Agents |
| --- | --- | --- | --- | --- |
| Boucle Devin : un échec H devient une PR sur le skill de la plateforme, puis un re-run vert | 3 | Prix Devin | Vrai échec existant (session 29d4bf3e) | devin-linkup-h, dig-r1-4 |
| Linkup lancé pendant que le coureur parle encore | 2 | Prix Gladia, effet démo | Schéma recommandé par Gladia | gladia |
| Profil salle bruyante : réglages Gladia, micro-casque, 10 phrases test | 1,5 | Fiabilité démo | Non testé en salle | gladia |
| Plan B course complète : liste d'attente ou courses proches | 2 | Fiabilité, UX | Lisbonne 2027 complète (vérifié) | synthèse, apres-course |
| 4e agent : Garmin Coach calé sur la date de course (Polar Flow en plan B) | 5 | Computer use | Il faut un compte Garmin + montre ; non testé | entraînement |
| Survol 3D du parcours et profil de dénivelé | 2 | Effet visuel | Prototype de 30 lignes fait ; concurrents existants | parcours 3D, dénivelé |
| Débrief d'arrivée : résultats Sporthive, photos, diplôme | 5 | Récit complet | Chaîne vérifiée à la main, pas avec H | après-course |
| Strava via l'API officielle (allure récente pour l'objectif) | 2 | Faible | Lecture seule | entraînement |

## Coupé

| Idée | Raison | Agents |
| --- | --- | --- |
| Booking et Airbnb | CGU interdisent les assistants IA (vérifié) | critique, dig-r1-1 |
| Scraper Strava | CGU interdisent le screen scraping (vérifié) | session Devin de Mathieu |
| Lisbonne comme démo principale | Semi complet, pas sur Njuko (vérifié) | dig-r1-0 |
| Train SNCF Connect, OUIGO | Captcha DataDome ou Cloudflare | voyage |
| Sous-agents H natifs | Le superviseur prend un slot ; 429 à capacité | devin-linkup-h, dig-r1-2 |
| Coach LLM maison, Pipecat/LiveKit/Vapi, suivi live, Google Earth piloté par H | Peu de points ou instable | plusieurs |

## Ce que chaque agent a trouvé

### Veille / état de l'art

- Meta Muse inscrit déjà à la voix sur RunSignup (US) : la voix + inscription seule n'est pas originale.
- Le jury H de San Francisco a primé confiance, contrôle humain et succès mesuré ; 2 de ses ingénieurs jugent à Paris.
- Aucun projet course à pied dans le H Showcase.

### Inscription

- Njuko : pas de compte jusqu'au paiement, pas de captcha, PPS pour non-licenciés (vérifié).
- Klikego : mode invité qui crée quand même un profil (vérifié).
- RunSignup, Race Roster, Active ont des API : moins de points computer use.

### Voyage

- Bloquent : SNCF Connect, easyJet, OUIGO, Hotels.com (depuis une IP datacenter, pas le navigateur H).
- Plus d'API libre : Booking, Expedia, Airbnb, Amadeus, Google Flights.
- Idée forte : hôtel choisi selon le vrai accès au départ, pas la distance.

### Gladia

- Barge-in, Linkup sur partiels, profil salle bruyante : le trio pour le prix.
- Offre gratuite : 1 session live à la fois, 3 h max.
- Pipecat, LiveKit, Vapi écartés : SDK JS direct dans le navigateur.

### Devin / Linkup / H

- Auto-réparation Devin via skills H versionnés : meilleur levier pour le prix Devin.
- Linkup hybride à 0,006 $ par appel.
- 3 slots H : pas de CI H pendant la démo.

### Entraînement

- Garmin et Polar : pas d'API d'écriture pour les particuliers, donc vrai terrain pour H.
- COROS a un MCP officiel, Strava est en lecture seule.
- Runna, Nike Run Club : appli mobile uniquement, hors de portée de H.

### Parcours 3D et dénivelé

- Tracé officiel exportable en KML sans compte.
- Rendu 3D maison sans clé : prototype fait.
- Piège : l'altitude mesure le fleuve sous les ponts, le D+ est faux sans correction.

### Après-course

- Résultats, photos et diplôme accessibles sans compte ni captcha (Sporthive, Marathon Photos).
- Transfert ou revente : Njuko, Klikego, Swika ; Lisbonne et Paris l'interdisent.

### Synthèse

- 48 idées fusionnées en 22, notées sur 100 avec la grille du jury.
- Top : inscription (93), séjour logistique (90), voix + portail (89), fiabilité (86), boucle Devin (82).

### Critique (avocat du diable)

- Scénario Lisbonne faux, Booking interdit, fiabilité non mesurée, cœur de démo rejoué, top 5 trop chargé (~34 h).
- N'a pas pu vérifier Meta Muse.

### Approfondissements (dig-r1-0 à 4)

- Lisbonne 2027 complète ; mauvaise épreuve visée (prova_id 3765 = marche de 4 km).
- Accor : meilleure option hôtel ; le portail doit s'ouvrir dès les cases de consentement.
- Tokens : ~230 à 260 k par run court ; 59,5 M restants, plafond ~2,8 M par run sur 21 runs.
- Boucle Devin faisable en ~3 h, sans clé API Devin (lancement manuel).
- Attente au portail : 19,5 min sans client, puis send_message, session terminée en succès.
