# Notation du jury : ce qui est fait, ce qui manque

État au 7 novembre 2026, 15 h, corrigé le 8 novembre 2026 (audit J11) pour l'orchestrateur et l'UX, d'après le code présent sur `main`. À mettre à jour à chaque PR qui fait avancer un critère.

Légende : ✅ fait et vérifié · 🟡 en cours ou partiel · ❌ pas commencé.

## Vue d'ensemble

| Critère | Poids | État | En une phrase |
| --- | ---: | :---: | --- |
| Use of Computer Use | 25 % | 🟡 | Les agents H tournent en vrai sur 3 sites, mais pas encore depuis l'application RunAI. |
| Technical execution & reliability | 25 % | 🟡 | CI et smoke tests en place ; orchestrateur codé (`runai/app/mission.py`), robustesse en cours ; taux de réussite mesurés manquants. |
| Usefulness & impact | 20 % | 🟡 | Problème réel et logistique propre à la course identifiés ; pas encore démontrés de bout en bout. |
| Originality & innovation | 15 % | 🟡 | Angle « logistique course » et voix qui pilote 3 agents choisis ; à montrer. |
| UX & user control | 10 % | 🟡 | Arrêt humain avant engagement, commandes vocales (`runai/voice/commands.py`, `runai/app/voice_ws.py`) et vue live (`runai/app/static/live.html`) codés ; rendu navigateur non vérifié par l'audit. |
| Demo clarity & Q&A | 5 % | 🟡 | Déroulé, plans de secours et questions du jury rédigés ; vidéo à tourner. |

## Détail par critère

### 1. Use of Computer Use (25 %)

| Fait | Preuve |
| --- | --- |
| ✅ Agent H `h/web-surfer-pro` opérationnel | `scripts/test_h.py`, smoke test manuel dans GitHub Actions |
| ✅ 3 agents H en parallèle sur de vrais sites (page d'inscription, hôtel, vol) | Benchmark du 7 nov. : 2 min 50 au total, en lecture seule |
| ✅ Une session H tient ~20 min en attente au portail puis reprend | [RECHERCHES_AGENTS.md](RECHERCHES_AGENTS.md) |

| Manque | Pour prendre les points |
| --- | --- |
| ❌ Inscription remplie jusqu'au paiement sur une course ouverte (Njuko ou Klikego) | Lisbonne est complète : prendre une course déjà testée |
| ❌ Agents lancés depuis RunAI, vues live à l'écran | Montrer les 3 agents en direct pendant le pitch, pas une vidéo accélérée |

Bonus visé : corriger un agent en cours à la voix (`send_message`).

### 2. Technical execution & reliability (25 %)

| Fait | Preuve |
| --- | --- |
| ✅ CI GitHub Actions : Ruff + Pytest sur chaque PR et sur `main` | `.github/workflows/ci.yml` |
| ✅ Smoke tests réels Linkup et Gladia sur chaque push `main`, H à la demande | `.github/workflows/smoke.yml` |
| ✅ Garde-fou contre les clés API committées | `tests/test_repo.py` |
| ✅ Temps mesurés : Linkup ~2 s, Gladia ~6 s, agent H 34 s à 2 min 50 | Benchmark du 7 nov. |

| Manque | Pour prendre les points |
| --- | --- |
| 🟡 Orchestrateur (backend) : Linkup → 3 sessions H → réponses typées | Codé (`runai/app/mission.py`, `runai/h/runner.py`) ; robustesse en cours (audit M1–M9) |
| ❌ Taux de réussite réels (5 runs par site) | Les chiffres « 4/5 » des docs sont des exemples, pas des mesures |
| ❌ Mode dégradé quand un site bloque | Plan B prévu dans [DEMO_ET_LIVRABLES.md](DEMO_ET_LIVRABLES.md) |
| ❌ Hébergement du test live (Render ou tunnel) | Nécessaire pour le livrable 6 |

Attention : le plan H Free a 3 slots ; banc de tests, dev et démo se les partagent.

### 3. Usefulness & impact (20 %)

| Fait | Preuve |
| --- | --- |
| ✅ Problème réel : inscription, hôtel et transport éparpillés sur plusieurs sites | Pitch « Dis-moi ta course, je prépare tout le déplacement » |
| ✅ Contraintes réelles vérifiées : course complète, CGU Booking anti-IA, captchas SNCF | [RECHERCHES_AGENTS.md](RECHERCHES_AGENTS.md) |

| Manque | Pour prendre les points |
| --- | --- |
| 🟡 Logistique course dans le résultat : retrait du dossard, accès au départ, hôtel choisi selon le temps d'accès | Codée (`runai/logistics/`, `runai/journey/planner.py`) ; corrections en cours (audit J4, J6, J7) ; non démontrée de bout en bout |

### 4. Originality & innovation (15 %)

| Fait | Preuve |
| --- | --- |
| ✅ Positionnement face aux 29 projets du H Showcase | [FEATURES_A_REPRENDRE.md](FEATURES_A_REPRENDRE.md) |
| ✅ Architecture « Linkup cherche, H agit » | [LINKUP.md](LINKUP.md) |

| Manque | Pour prendre les points |
| --- | --- |
| ❌ Une phrase vocale qui pilote 3 agents en même temps | Différence avec la démo classique « agent qui réserve un voyage » |
| 🟡 Boucle Devin : un échec H devient une PR, puis un re-run vert | Option, ~3 h, seulement si le cœur tient |

### 5. UX & user control (10 %)

| Fait | Preuve |
| --- | --- |
| ✅ Règle : rien n'est payé, réservé ni soumis | Docs et prompts H en lecture seule |

| Manque | Pour prendre les points |
| --- | --- |
| 🟡 Portail « l'agent remplit, l'humain signe » sur chaque case santé, règlement, RGPD et avant paiement | Arrêt codé (`runai/safety.py` `detect_stop_point`, statut `stopped_before_commitment`, `runai/app/static/live.html`) ; garde-fous durcis par l'audit (S1, S2, M3) ; non vérifié en live |
| 🟡 Interface vocale Gladia : transcription live, « stop », « pause », « reprends » | Codée (`runai/app/voice_ws.py`, `runai/voice/commands.py`) ; non vérifiée en live par l'audit |
| 🟡 Vue live de chaque agent | `runai/app/static/live.html` ; rendu non vérifié par l'audit |

### 6. Demo clarity & Q&A (5 %)

| Fait | Preuve |
| --- | --- |
| ✅ Déroulé de 3 min, plans de secours, questions probables du jury | [DEMO_ET_LIVRABLES.md](DEMO_ET_LIVRABLES.md) |

| Manque | Pour prendre les points |
| --- | --- |
| ❌ Vidéo de démo | Livrable 4 |
| ❌ Durées annoncées = durées mesurées en conditions réelles | Remesurer sur le scénario final |

## Livrables Builderbase

| # | Livrable | État |
| --- | --- | :---: |
| 1 | Project Name : RunAI | ✅ |
| 2 | Github Repo : github.com/IbaDemesy/RunAI | ✅ |
| 3 | Fiche H Showcase | 🟡 brouillon dans [DEMO_ET_LIVRABLES.md](DEMO_ET_LIVRABLES.md) |
| 4 | Vidéo de démo | ❌ |
| 5 | Project Description | 🟡 brouillon |
| 6 | How do I test your product live | 🟡 brouillon, dépend de l'hébergement |

## Prix bonus

| Prix | Ce qu'on montre | État |
| --- | --- | :---: |
| Gladia (1 000 €) | Voix comme seule interface, vocabulaire course, transcription live, interruption | 🟡 codé (`runai/voice/`, `runai/app/voice_ws.py`), non vérifié en live |
| Best use of Devin (1 000 €) | Workflow de 16 agents d'exploration, PR, CI, Devin Review ; boucle d'auto-réparation en option | 🟡 |
| LinkedIn et X (500 € chacun) | Un post par plateforme | ❌ |

Aucun barème officiel n'est publié pour les prix sponsors : ces pistes sont des stratégies, pas des garanties.
