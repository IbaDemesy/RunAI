# Spike : ossature de l'orchestrateur (axe 11)

Prototype FastAPI inspiré de [Pricehunter](https://github.com/lmveprog/pricehunter) (MIT) : une session H par mission, suivi en direct, arrêt avant paiement. **Aucune session H réelle n'a été lancée** : l'adaptateur réel est vérifié contre le code installé du SDK `hai-agents` 1.4.3, et tout le reste tourne sur l'adaptateur mock.

## Ce qui est prouvé (avec le mock)

- `POST /missions` crée 3 missions (inscription, hôtel, transport) lancées **en parallèle**.
- `GET /missions/{id}/events` : flux SSE (`state`, `step`, `screenshot`, `live_view`, `message`, `answer`, `error`). L'historique est rejoué, la reprise se fait via `Last-Event-ID` (ou `?from_seq=`) sans doublon, et le flux se ferme en état terminal.
- `POST /missions/{id}/pause | resume | message | cancel`. Si l'agent attend l'humain (outil `request_human`), le `message` devient le résultat de l'outil, sinon c'est un `send_message` (correction en cours de route).
- Machine à états : `queued → running → waiting_human ⇄ running → ready_to_pay`, plus `failed` et `cancelled` (terminaux). Une transition interdite renvoie un 409.
- File FIFO devant les slots H : 3 slots locaux, et en tête de file le quota H de l'org (`GET /sessions/quota`) est vérifié, car les autres équipes prennent les mêmes slots. Si `available == 0`, on re-vérifie toutes les `poll_s` secondes jusqu'à `max_wait_s` (600 s), puis la mission passe en `failed` (`h_quota_timeout`).
- Une session `ready_to_pay` (H `idle`) **garde son slot** : la mission suivante reste en file jusqu'à un `cancel`. L'arrêt du serveur annule toutes les sessions.
- Contrats Pydantic `InscriptionAnswer`, `HotelAnswer`, `TransportAnswer`, envoyés à H via `overrides["agent.answer_format"]`. Un filtre côté serveur (`check_answer`) agit ainsi : `payment_submitted` donne `failed` et annule la session ; `blocked`, un budget dépassé, une mauvaise distance ou `ready_for_payment=false` donnent `waiting_human` avec la raison.

## SDK hai-agents 1.4.3 : signatures lues dans le code installé

| Besoin | Appel (`AsyncClient().sessions`) | Remarque |
| --- | --- | --- |
| Créer | `create_session(agent, messages, overrides, max_time_s, idle_timeout_s, timezone, queue)` | `queue=True` : file côté H au lieu d'un 429 |
| Réponse typée | `overrides={"agent.answer_format": Model.model_json_schema()}` | Même chose que ce que fait `start_session(answer_schema=...)` du SDK |
| Outil humain | `overrides={"agent.tools": [{name, description, input_schema}]}` | L'appel arrive dans `ActiveStateChangeEvent` (`awaiting_tool_results`, `pending_tool_calls`) |
| Suivre | `get_session_changes(id, from_index, include_events, wait_for_seconds)` | Long-poll, `None` sur un 204. Curseur : `first_index + len(new_events)` |
| Vue live | `Session.agent_view_url` + événement `LiveViewUrlEvent.data.live_view_url` | Aussi `share_session(id) -> ShareLink.share_url` (lien public) |
| Pause / reprise | `pause_session(id)`, `resume_session(id)` | 202 asynchrone, 409 si `queued` ou terminée (docs H) |
| Message | `send_session_messages(id, request=SendSessionMessagesRequestBody_UserMessage(message=...))` | Reprend une session en pause, relance une session finie (docs H) |
| Résultat d'outil | `send_session_tool_results(id, request=ToolResultEvent(tool_req=ToolRequest(...), result=...))` | |
| Annuler | `cancel_session(id)` (HTTP DELETE) | Un 409 lève `ApiError`, pas une classe dédiée |
| Quota | `get_session_quota() -> QuotaStatus(limit, active, available)` | |

Ces appels sont testés dans `tests/test_real_adapter.py`, avec un faux client qui renvoie de **vrais types du SDK** (`SessionChanges`, `SessionEventZero_*`, `ToolRequest`), et par `inspect.signature` sur `AsyncSessionsClient`.

## Résultats mesurés (local, mock, uvicorn sur 127.0.0.1)

`python bench_sse.py --trips 10 --speed 1` : 10 voyages de 3 missions, puis une 4e mission mise en file à chaque voyage. Le détail est dans `bench_results.json`.

| Mesure | Médiane | Max |
| --- | --- | --- |
| Latence SSE, publication → réception client (390 événements en direct) | 0,83 ms (p95 2,64 ms) | 4,73 ms |
| `POST /missions` (3 missions) | 4,1 ms | 12,2 ms |
| `message` → événement `running` reçu en SSE | 2,9 ms | 5,2 ms |
| `pause` aller-retour HTTP | 1,3 ms | 1,5 ms |
| `cancel` d'une mission → démarrage de la mission en file | 2,1 ms | 2,9 ms |
| 3 missions jusqu'à `ready_to_pay` (scénario mock d'environ 4 s, avec une validation humaine) | 4,02 s | 4,03 s |

Tests : `pytest spikes/orchestrateur` donne **25 tests réussis** (machine à états, filtre de réponses, file et quota, pause, reprise, message, annulation, API HTTP et SSE de bout en bout, adaptateur réel).

**Non mesuré** : la latence réelle de H (pause en 202 asynchrone, délai du long-poll `changes`, délai de libération du slot après un cancel), et la question de savoir si H accepte tels quels nos schémas `answer_format` (champs `format: date`).

## Relancer

```bash
cd spikes/orchestrateur
../../.venv/bin/pip install -r requirements.txt   # fastapi (absent de requirements.txt à la racine)
../../.venv/bin/python -m pytest -q .
../../.venv/bin/python bench_sse.py --trips 10
RUNAI_H_ADAPTER=mock RUNAI_MOCK_SPEED=1 ../../.venv/bin/uvicorn runai_orch.app:app --port 8800
# RUNAI_H_ADAPTER=real utilise HAI_API_KEY (consomme un slot H par mission !)
```

## Fichiers

- `runai_orch/contracts.py` : états, contrats `answer_format`, schémas de l'API
- `runai_orch/state.py` : machine à états et bus d'événements par mission (historique et abonnés SSE)
- `runai_orch/scheduler.py` : file FIFO, slots et quota H
- `runai_orch/orchestrator.py` : missions, prompts, mapping des événements, filtre serveur, commandes
- `runai_orch/adapters/{base,mock,real}.py` : adaptateur abstrait, mock rejouable, SDK réel
- `runai_orch/app.py` : routes FastAPI

## Reste à faire pour la démo

- Un run H réel de l'adaptateur `real` (1 slot, ~3 min) pour valider le mapping des événements et `answer_format`.
- Un proxy des captures : les URL d'images H demandent le bearer, comme `http.get` dans Pricehunter.
- Le branchement de Gladia (pause, message) et de Linkup (champs du `TripRequest`), la persistance (aujourd'hui tout est en mémoire), et le front de la vue live.
