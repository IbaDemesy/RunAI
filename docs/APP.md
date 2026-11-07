# Application web et portail de contrôle (`runai/app/`)

Squelette de l'application que verra le jury. Il tourne **sans aucune clé** grâce à des implémentations factices ; les vraies briques H, voix et Linkup se branchent derrière des interfaces minimales.

## Lancer la démo

```bash
python -m runai.app                 # http://127.0.0.1:8000
RUNAI_DEMO_DELAY=0.5 python -m runai.app   # agents simulés plus rapides
```

Variables propres à l'application : `RUNAI_APP_HOST`, `RUNAI_APP_PORT` (défaut `127.0.0.1:8000`) `RUNAI_DEMO_DELAY` (secondes entre deux actions simulées, défaut 1,5) et `RUNAI_BASIC_AUTH` (`utilisateur:motdepasse`, met un mot de passe devant toute l'app sauf `/api/health`). Les traces vont dans `RUNAI_TRACES_DIR` (socle).

Parcours : on tape la course ou on clique sur **Dire la course** (micro → `/api/transcribe`). Une mission est créée : recherche de la course, puis trois agents en parallèle (inscription, hébergement, transport), chacun dans une carte avec son statut (`StepStatus`), sa dernière action, sa vue live, et des boutons pause / reprise / message. Le **portail** liste, pour chaque agent arrêté, le point d'arrêt (`StopPoint`), la page atteinte, le prix et ce que l'humain doit faire lui-même. Tout est journalisé dans la trace (`TraceWriter`) et poussé en direct par SSE.

## Héberger le POC (Render)

`render.yaml` configures a single-process Render service with `RUNAI_MODE=live`, `uvicorn runai.app.server:create_app --factory` and the `/api/health` probe. Mission snapshots, SSE envelopes, framing context, launch plans and the latest journey are saved atomically as redacted `mission-store.v1` JSON documents in `<RUNAI_TRACES_DIR>/missions/<mission_id>.json`. Active updates are coalesced to at most one write every 0.5 seconds; terminal states are flushed immediately. On startup, saved missions are restored read-only, including the latest recap exports and `Last-Event-ID` replay (the terminal event stream then closes). Interrupted missions become failed with the `server_restarted` limitation; agents are never resumed automatically. Storage is local to this one process: configure `RUNAI_TRACES_DIR` on a persistent Render disk to retain data across deployments; ephemeral disks and lost volumes cannot be recovered.

1. Render → **New → Blueprint**, choisir ce dépôt et la branche `main`.
2. Renseigner `RUNAI_BASIC_AUTH` (obligatoire : `render.yaml` fixe `RUNAI_PUBLIC=1` et l'app refuse alors de démarrer en mode live sans mot de passe), `HAI_API_KEY`, `LINKUP_API_KEY`, `GLADIA_API_KEY` (facultative, voix).
3. Garde-fous crédits : `RUNAI_H_MAX_STEPS=40`, `RUNAI_H_MAX_TIME_S=600`. Les slots H sont partagés entre toutes les missions live ; en démo, les missions ne s'attendent pas.

Plan gratuit : le service s'endort après ~15 min sans visite (réveil ~1 min, missions en cours perdues). Ouvrir la page avant une démo, ou passer `plan: starter` pour éviter la veille.

Couper le service après le hackathon.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `ports.py` | Protocols attendus des autres briques : `RaceSearch` (Linkup), `BrowserAgents` / `AgentRun` (H), `Transcriber` (Gladia) |
| `mission.py` | `MissionService` : orchestration, limite de concurrence, pause / reprise / message, trace, abonnements SSE |
| `tasks.py` | Consignes envoyées aux agents (toujours via `guard_task()`, profil fictif) et action humaine par `StopPoint` |
| `fakes.py` | Implémentations factices : course de démo (Milan ou Lisbonne, données factices), agents scriptés, transcription fixe |
| `server.py` | Backend FastAPI et `create_app(service)` |
| `auth.py` | Mot de passe HTTP Basic optionnel (`RUNAI_BASIC_AUTH`) |
| `static/` | Page web (HTML/CSS/JS sans build) et vue live simulée |

## API

| Méthode | Route | Rôle |
| --- | --- | --- |
| `POST` | `/api/missions` `{"query": "..."}` | Crée et lance une mission |
| `GET` | `/api/missions/{id}` | État complet (avec la trace) |
| `GET` | `/api/missions?user_id=&limit=20&status=` | Request history (newest first, redacted `MissionSummary` list, `[]` when empty) |
| `GET` | `/api/missions/{id}/summary` | `MissionSummary` of one mission (404 if unknown) |
| `GET` | `/api/missions/{id}/events` | Flux SSE : `snapshot`, puis `trace` et `mission` à chaque changement, `end` à la fin |
| `POST` | `/api/missions/{id}/pause` · `/resume` | Pause / reprise de tous les agents |
| `POST` | `/api/missions/{id}/steps/{kind}/pause` · `/resume` · `/message` `{"text": "..."}` | Contrôle d'un agent (`kind` : `registration`, `accommodation`, `transport`) |
| `POST` | `/api/transcribe` (corps : audio brut) | Transcription d'un enregistrement court |
| `GET` | `/api/live/{session_id}` | Données de la vue live simulée |

## Request history (`user_id` contract)

There are no accounts: the frontend generates an opaque runner id once (e.g. `crypto.randomUUID()` stored in `localStorage`) and sends it when a framing starts:

```json
POST /api/framings
{"text": "...", "channel": "text", "user_id": "3f2b9c1e-...-a7"}
```

- `user_id` is optional, 1-64 chars, `[A-Za-z0-9_-]` only (otherwise 422). Never put an email or a name in it.
- It is copied to the `FramingSession` and to the mission created on confirm; `GET /api/framings/{id}` echoes it.
- `GET /api/missions?user_id=<id>` lists that runner's missions, newest first. Query params: `limit` (1-100, default 20), `status` (`searching`, `running`, `awaiting_human`, `completed`, `failed`, `cancelled`). Without `user_id`, every mission held by the instance is listed (the app is behind `RUNAI_BASIC_AUTH`).
- Each item is a `MissionSummary` (`mission_summary.v1`): `mission_id`, `framing_id`, `user_id`, `mode`, `status`, `created_at`, `finished_at`, `race` (`name`, `city`, `country`, `race_date`, `distance_km`), `origin`, `date_range` (`[arrival, departure]`), `budget_eur`, `total_price_eur` (sum of step `price_eur`, `null` if no price yet), `steps` (`kind`, `status`, `stop_point`, `price_eur`, `url`), `headline` (English, e.g. `Prepared up to payment on 3 of 3 steps`) and `replay_available`.
- Missions live in memory: the history covers what the instance holds (including missions restored at startup, if enabled).

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
- Mission recovery requires the same persistent traces volume; a process crash can lose up to 0.5 seconds of active updates. Older recap revisions remain in-memory only.
- Pas encore vérifié : affichage de la vue live H réelle dans une `iframe` (en-têtes de la plateforme H), lien « Ouvrir la vue live » prévu en repli.
- Transcription par enregistrement court ; les partiels Gladia en direct et les commandes vocales relèvent de la brique voix.
