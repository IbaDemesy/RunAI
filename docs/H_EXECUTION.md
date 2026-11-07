# Exécution H (`runai/h/`)

## Publishing a trace

Before committing a replay fixture or sending a trace to Devin, run
`python -m scripts.scrub_trace traces/input.jsonl traces/publishable.jsonl`.
The scrubber masks provider credentials and personal contact details, removes
private H view and trajectory URLs, and preserves public `share_url` links.
It prints the number of events kept and fields scrubbed. Publish only the
scrubbed output; `find_violations` in `scripts.scrub_trace` checks the same
invariants enforced by the repository fixture tests.

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

## Public share link

Each new session requests a public link through `sessions.share_session()`. Relative share paths
use the owning client's base URL origin (scheme and host), falling back to
`https://agp.eu.hcompany.ai` when unavailable; absolute URLs are preserved. `run.share_url`
and `StepResult.data['share_url']` expose the link. Without a `LiveViewUrlEvent`,
`live_view_url` uses this public link; an explicit live-view event takes precedence.
Sharing failures produce a warning trace without interrupting the session. The private
`agent_view_url` remains separate and may require an H login. The `session_created` trace
and result data include `h_key`, the account name only, never its secret value.

## Outcome and error_code mapping

| H signal | Step result |
| --- | --- |
| `outcome=blocked` | `failed`, with `Blocked by the site (captcha/anti-bot or login wall)` |
| `outcome=infeasible` | `failed`, with the first 200 answer characters and `retryable=false` |
| `outcome=partial` | Existing status and stop-point detection, with `partial=true` |
| Other or missing outcome | Existing H status, captcha-marker and stop-point detection |
| Failed H status with `error_code` | Uses the error code if no error text is available |

Both `outcome` and `error_code` are included in result data. Error codes such as
`environment_error`, `no_answer`, `answer_validation`, `timeout`, `insufficient_credit`,
and `internal` are preserved unchanged.

### Environment overrides

`RUNAI_H_OVERRIDES` optionally supplies a JSON object of H agent overrides, for example
`{"agent.environments[kind=web].settle_s": 0.5, "agent.environments[kind=web].lazy": true}`.
Explicit `start(overrides=...)` values win over environment values, and `start_url`
is applied last. An invalid JSON object raises `ValueError` when constructing `HRunner`.
With the variable unset, behavior is unchanged.
