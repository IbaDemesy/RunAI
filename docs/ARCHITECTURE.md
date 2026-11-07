# Architecture du code RunAI

Socle commun dans `runai/`. Chaque brique a son dossier, pour que plusieurs agents travaillent en parallèle sans se marcher dessus.

| Dossier | Rôle | Dépend de |
| --- | --- | --- |
| `runai/config.py` | Clés et réglages lus depuis `.env` (`RUNAI_H_AGENT`, `RUNAI_H_MAX_CONCURRENCY`, `RUNAI_TRACES_DIR`) | — |
| `runai/models.py` | Modèles Pydantic partagés : `RunnerProfile`, `Race`, `StepResult`, `StopPoint`, `AgentQuestion`, `TraceEvent` | — |
| `runai/safety.py` | Garde-fou commun : `guard_task()` ajoute les règles d'arrêt au prompt H, `detect_stop_point()` repère paiement, compte, santé, consentement, soumission | `models` |
| `runai/tracing.py` | Journal JSONL d'une mission (`traces/`, ignoré par git) : replay, debug, réparation Devin | `models` |
| `runai/h/` | Exécution H : lancer, suivre, pause, message, trace, limite de sessions simultanées | socle |
| `runai/voice/` | Voix Gladia en direct et commandes vocales | socle |
| `runai/search/` | Recherche Linkup : fiche course sourcée | socle |
| `runai/app/` | Application web : `MissionService` (orchestrateur), portail, questions `ask_user`, vues live. `ports.py` = Protocols, `fakes.py` = mode démo, `real.py` = Linkup/H/Gladia | socle, interfaces des autres briques |
| `web/flyover/` | Survol 3D du parcours (MapLibre) | — |

## Flux d'une mission (V1)

```
Utilisateur (texte, ou voix Gladia : runai/voice)
        │
        ▼
MissionService (runai/app/mission.py) : orchestrateur déterministe, FastAPI + SSE vers le portail
        │ 1. recherche
        ├──► Linkup (runai/search) : fiche course sourcée et géocodée
        │ 2. trois agents H en parallèle (runai/h : pool multi-clés, quotas, 60 étapes / 900 s)
        ├──► H inscription  : Njuko (lien officiel de la course uniquement)
        ├──► H hébergement  : Accor, budget max demandé puis vérifié côté serveur
        └──► H transport    : Trenitalia, échec propre en cas de captcha
                 │  outil custom ask_user ──► question dans le portail ──► réponse renvoyée à H
                 │  pause / reprise / message humain (passent par guard_task)
                 ▼
        StopPoint : arrêt avant paiement, consentement, santé, compte ou soumission
        │
        ▼
Portail : tracé de mission, cartes agents, questions, « Ligne d'arrivée » (ce que l'utilisateur signe et paie)
Traces JSONL (runai/tracing) ──► replay, debug, réparation par Devin
```

- L'orchestrateur est du code, pas un LLM : l'enchaînement, les quotas et l'arrêt avant engagement sont garantis par le code. L'autonomie est dans les sessions H.
- Une question `ask_user` expire avant la fin de la session H (`question_timeout_s ≤ max_time_s - 60`).
- Le plafond hôtel retenu est le plus bas des budgets donnés (réponses aux questions de budget, requête).
- Mode démo (`RUNAI_DEMO=1`, ou clés absentes) : mêmes Protocols, agents simulés par `fakes.py`.

## Règles communes

- Ne pas modifier le socle dans une PR de brique ; proposer le changement à part.
- Toute tâche H passe par `guard_task()`. Aucun paiement, réservation, soumission, création de compte ni case de consentement.
- Profil fictif `RunnerProfile()` par défaut, jamais de vraies données personnelles.
- Plan H Free : 3 sessions simultanées pour toute l'organisation (CI, dev, démo). Les tests unitaires n'appellent pas les API réelles.
- Pas de Booking.com, TAP, Trainline (captcha) ni Klikego (CGU), voir [EXPLORATION.md](EXPLORATION.md).
