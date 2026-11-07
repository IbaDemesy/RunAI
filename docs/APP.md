# Application web et portail de contrôle (`runai/app/`)

Squelette de l'application que verra le jury. Il tourne **sans aucune clé** grâce à des implémentations factices ; les vraies briques H, voix et Linkup se branchent derrière des interfaces minimales.

## Lancer la démo

```bash
python -m runai.app                 # http://127.0.0.1:8000
RUNAI_DEMO_DELAY=0.5 python -m runai.app   # agents simulés plus rapides
```

Variables propres à l'application : `RUNAI_APP_HOST`, `RUNAI_APP_PORT` (défaut `127.0.0.1:8000`) et `RUNAI_DEMO_DELAY` (secondes entre deux actions simulées, défaut 1,5). Les traces vont dans `RUNAI_TRACES_DIR` (socle).

Parcours : on tape la course ou on clique sur **Dire la course** (micro → `/api/transcribe`). Une mission est créée : recherche de la course, puis trois agents en parallèle (inscription, hébergement, transport), chacun dans une carte avec son statut (`StepStatus`), sa dernière action, sa vue live, et des boutons pause / reprise / message. Le **portail** liste, pour chaque agent arrêté, le point d'arrêt (`StopPoint`), la page atteinte, le prix et ce que l'humain doit faire lui-même. Tout est journalisé dans la trace (`TraceWriter`) et poussé en direct par SSE.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `ports.py` | Protocols attendus des autres briques : `RaceSearch` (Linkup), `BrowserAgents` / `AgentRun` (H), `Transcriber` (Gladia) |
| `mission.py` | `MissionService` : orchestration, limite de concurrence, pause / reprise / message, trace, abonnements SSE |
| `tasks.py` | Consignes envoyées aux agents (toujours via `guard_task()`, profil fictif) et action humaine par `StopPoint` |
| `fakes.py` | Implémentations factices : course de démo (Milan ou Lisbonne, données factices), agents scriptés, transcription fixe |
| `server.py` | Backend FastAPI et `create_app(service)` |
| `static/` | Page web (HTML/CSS/JS sans build) et vue live simulée |

## API

| Méthode | Route | Rôle |
| --- | --- | --- |
| `POST` | `/api/missions` `{"query": "..."}` | Crée et lance une mission |
| `GET` | `/api/missions/{id}` | État complet (avec la trace) |
| `GET` | `/api/missions/{id}/events` | Flux SSE : `snapshot`, puis `trace` et `mission` à chaque changement, `end` à la fin |
| `POST` | `/api/missions/{id}/pause` · `/resume` | Pause / reprise de tous les agents |
| `POST` | `/api/missions/{id}/steps/{kind}/pause` · `/resume` · `/message` `{"text": "..."}` | Contrôle d'un agent (`kind` : `registration`, `accommodation`, `transport`) |
| `POST` | `/api/transcribe` (corps : audio brut) | Transcription d'un enregistrement court |
| `GET` | `/api/live/{session_id}` | Données de la vue live simulée |

## Brancher une vraie brique

Écrire une classe qui respecte le Protocol de `ports.py`, puis la passer à `MissionService` :

```python
service = MissionService(LinkupRaceSearch(), HBrowserAgents(), GladiaTranscriber())
app = create_app(service)
```

Contrat côté H (`BrowserAgents.start`) :

- `task` est déjà passé par `guard_task()` ; l'agent reçoit aussi `race` et le profil fictif.
- `on_event(TraceEvent)` peut être appelé depuis un autre thread (SDK synchrone) : l'application le recale sur sa boucle. Mettre `data["url"]` pour afficher la page courante ; `source` commençant par `agent` met à jour la « dernière action » de la carte.
- `AgentRun.live_view_url` : URL absolue (vue live H) ou chemin relatif à l'application.
- `AgentRun.wait()` renvoie un `StepResult`. Si l'agent ne renseigne pas `stop_point`, l'application applique `detect_stop_point()` sur le résumé et passe l'étape en `stopped_before_commitment`.

## Limites connues

- Mode démo uniquement : aucune vraie brique n'est encore branchée, aucun appel H, Gladia ou Linkup.
- Missions en mémoire (perdues au redémarrage) ; la trace JSONL reste sur disque.
- Pas encore vérifié : affichage de la vue live H réelle dans une `iframe` (en-têtes de la plateforme H), lien « Ouvrir la vue live » prévu en repli.
- Transcription par enregistrement court ; les partiels Gladia en direct et les commandes vocales relèvent de la brique voix.
