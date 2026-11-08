# Notation du jury : ce qui est fait, ce qui manque

Code review on 8 November 2026 against `d320c2a`. This audit uses offline
fakes/fixtures: historical live benchmarks below were not revalidated.
Implemented code is not evidence of a successful live demo.

Légende : ✅ fait et vérifié · 🟡 en cours ou partiel · ❌ pas commencé.

## Vue d'ensemble

| Critère | Poids | État | En une phrase |
| --- | ---: | :---: | --- |
| Use of Computer Use | 25 % | 🟡 | H integration exists in the app; deterministic tests, live demo not revalidated. |
| Technical execution & reliability | 25 % | 🟡 | CI and orchestration exist; live success rates not revalidated. |
| Usefulness & impact | 20 % | 🟡 | Problème réel et logistique propre à la course identifiés ; pas encore démontrés de bout en bout. |
| Originality & innovation | 15 % | 🟡 | Angle « logistique course » et voix qui pilote 3 agents choisis ; à montrer. |
| UX & user control | 10 % | partial | Shell, human handoff and voice implemented; browser and live-demo checks still pending. |
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
| Partial: app launch and live views implemented | `runai/app/mission.py`, `runai/app/static/live.html`; live presentation not revalidated |

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
| Partial: orchestration is implemented, not missing | `runai/app/mission.py`, `tests/e2e/test_demo_journey.py` (fakes); fresh live evidence still needed |
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
| Partial: logistics in JourneyPlan and exports | `runai/journey/planner.py`, `tests/test_journey_planner.py`; per-leg prices incomplete (J10 / JURY-W1-7) |

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
| Partial: human handoff and pre-commitment stops implemented | `runai/app/static/app.js`, offline mission tests; real journey not revalidated |
| Partial: voice interface implemented | `runai/app/voice_ws.py`, `web/voice/voice-input.js`; no real Gladia call during this audit |
| Partial: live view implemented | `runai/app/static/live.html`; browser rendering not revalidated |

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
