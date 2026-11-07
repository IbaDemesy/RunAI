# Exécution H (`runai/h/`)

Module qui lance et pilote les sessions `h/web-surfer-pro` (SDK `hai-agents`, client async).

## Utilisation

```python
from runai.h import HRunner, HStep
from runai.models import StepKind

async with HRunner() as runner:
    # Une étape, avec suivi des événements
    run = await runner.start(StepKind.accommodation, "Cherche un hôtel près du départ", mission_id="m1",
                             start_url="https://…", max_steps=40)
    print(run.agent_view_url)
    await run.pause()                      # 202 asynchrone : attendre `paused` avec run.wait_for_status({"paused"})
    await run.send_message("Plutôt sous 150 € la nuit")   # reprend aussi une session en pause
    result = await run.wait(on_event=print, timeout_s=900)  # StepResult

    # Plusieurs étapes en parallèle, une seule trace de mission
    results = await runner.run_many([HStep(StepKind.registration, "…"), HStep(StepKind.accommodation, "…")],
                                    mission_id="m2")
```

- Toute tâche passe par `guard_task()` ; la réponse finale passe par `detect_stop_point()` (statut `stopped_before_commitment`).
- Chaque événement H est écrit dans la trace (`TraceWriter`), allégé : sans captures d'écran ni HTML, textes coupés à 500 caractères. Les contrôles (`pause`, `resume`, `message`, `force_answer`, `cancel`) et le résultat sont tracés aussi.
- Plusieurs clés H : `HRunner()` lit `HAI_API_KEY`, puis `HAI_API_KEY_2`, `HAI_API_KEY_3`… (optionnelles, une par organisation H). Chaque clé a son propre quota et un plafond local `RUNAI_H_MAX_CONCURRENCY` (par clé). Avant chaque création, le pool interroge `get_session_quota()` de chaque clé ayant un slot local et choisit celle qui a le plus de slots libres. La clé utilisée est tracée (`h_key`, par nom, jamais la valeur) et exposée par `run.account.name` ; les contrôles passent par le client de cette clé. On peut aussi passer `HRunner(accounts=[HAccount(...), …])`.
- La session est créée avec `queue=False` : en cas de course avec une autre session, le `429` est rattrapé et on réessaie jusqu'à `quota_timeout_s`, puis `HQuotaTimeout`.
- `agent`, `messages` et `queue` ne sont pas surchargeables (`ValueError`) : la tâche passe toujours par `guard_task()`. Les messages de pilotage (`send_message`) sont aussi suivis des règles d'arrêt.
- `wait(timeout_s=…)` annule la session au-delà du délai pour libérer le slot, de même si la tâche qui attend est annulée ; `async with run:` annule une session abandonnée. Une session interactive arrêtée sur `idle` garde son slot jusqu'à `close()`.
- Une session one-shot passe brièvement par `idle` avant `completed` (observé) : le suivi attend l'état terminal. Avec `idle_timeout_s` (session interactive), il s'arrête sur `idle`.

## Démo

```bash
python -m scripts.h_demo                        # ouvre example.com et lit le titre
python -m scripts.h_demo --start-url --steer    # navigateur déjà sur l'URL ; pause, reprise, message
```

Le script affiche le quota de chaque clé, vérifie qu'un slot est libre, lance une seule session courte en lecture seule et affiche événements, résultat et chemin de la trace.

## Mesures réelles (7 nov. 2026, example.com, une session à la fois)

| Run | Pas | Durée | Coût | Observation |
| --- | --- | --- | --- | --- |
| Sans `start_url`, avec pause/reprise/message | 3 | 27 s | 0,0076 $ | Démarre sur Bing. Pause : appel 0,5 s, état `paused` 1,5 s après la demande. `flow_event` pause/resume et message reçus |
| Avec `start_url` | 1 | 13 s | 0,0028 $ | L'override `agent.environments[kind=web].start_url` fonctionne avec `h/web-surfer-pro` |

Aucun `LiveViewUrlEvent` n'a été émis dans ces deux runs : `live_view_url` retombe alors sur l'`agent_view_url` (page Agent View de la plateforme H, connexion requise). Un lien public sans clé passerait par le [partage de session](https://hub.hcompany.ai/agents-api/sessions/share.md), non branché ici.
