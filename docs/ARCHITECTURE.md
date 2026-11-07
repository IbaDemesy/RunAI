# Architecture du code RunAI

Socle commun dans `runai/`. Chaque brique a son dossier, pour que plusieurs agents travaillent en parallèle sans se marcher dessus.

| Dossier | Rôle | Dépend de |
| --- | --- | --- |
| `runai/config.py` | Clés et réglages lus depuis `.env` (`RUNAI_H_AGENT`, `RUNAI_H_MAX_CONCURRENCY`, `RUNAI_TRACES_DIR`) | — |
| `runai/models.py` | Modèles Pydantic partagés : `RunnerProfile`, `Race`, `StepResult`, `TraceEvent` | `redaction` |
| `runai/redaction.py` | Masquage récursif des clés configurées avant sérialisation publique | — |
| `runai/contracts/` | Contrats versionnés de cadrage, mission, événements SSE, JourneyPlan ; fixtures communes | `models`, `redaction` |
| `runai/framing/` | Extraction heuristique, dialogue et résumé révisé ; confirmation obligatoire puis `LaunchPlan` | `contracts`, `app/tasks`, `app/providers` |
| `runai/safety.py` | Garde-fou commun : `guard_task()` ajoute les règles d'arrêt au prompt H, `detect_stop_point()` repère paiement, compte, santé, consentement, soumission | `models` |
| `runai/tracing.py` | Journal JSONL d'une mission (`traces/`, ignoré par git) : replay, debug, réparation Devin | `models` |
| `runai/h/` | Exécution H : lancer, suivre, pause, message, trace, limite de sessions simultanées | socle |
| `runai/voice/` | Voix Gladia en direct et commandes vocales | socle |
| `runai/search/` | Recherche Linkup : candidats multi-courses et fiche course sourcée | socle, `contracts` |
| `runai/journey/` | Projection de choix connus en JourneyPlan révisé, sans géométrie ni horaires inventés | `contracts`, `logistics` |
| `runai/planning/` | Preuves métier, budget/éligibilité et snapshot commun des exports HTML/PDF/ICS | `contracts`, `quote`, `logistics`, `recap` |
| `runai/app/` | FastAPI, sélection live/demo/replay, orchestration des missions confirmées, projection Journey, exports et shell carte/voix | socle, `framing`, `journey`, `planning` |
| `web/flyover/` | Player Journey MapLibre, timeline de repli accessible et survol du parcours | contrat Journey JS, MapLibre |
| `web/voice/` | Capture audio et commandes vocales du navigateur, cadrage/agents/caméra distincts | API transcription, shell |

## Règles communes

- Ne pas modifier le socle dans une PR de brique ; proposer le changement à part.
- Toute tâche H passe par `guard_task()`. Aucun paiement, réservation, soumission, création de compte ni case de consentement.
- Profil fictif `RunnerProfile()` par défaut, jamais de vraies données personnelles.
- Plan H Free : 3 sessions simultanées pour toute l'organisation (CI, dev, démo). Les tests unitaires n'appellent pas les API réelles.
- Pas de Booking.com ni de TAP (CGU), voir [EXPLORATION.md](EXPLORATION.md).
