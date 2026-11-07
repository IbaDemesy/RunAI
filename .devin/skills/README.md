# Skills Devin

Skills officiels des éditeurs du stack RunAI, copiés tels quels (format `SKILL.md`, chargés automatiquement par Devin depuis `.devin/skills/`). Ne pas les modifier ici : les mettre à jour depuis leur source.

| Skills | Source | Commit | Licence |
|---|---|---|---|
| `hai-agents`, `hai-qa-via-cli` | [hcompai/computer-use-agents-demos](https://github.com/hcompai/computer-use-agents-demos/tree/main/skills) | fd9e283 | MIT |
| `gladia-*` (6) | [gladiaio/skills](https://github.com/gladiaio/skills) | 3355562 | MIT |
| `linkup-*` (5) | [LinkupPlatform/skills](https://github.com/LinkupPlatform/skills) | dfc1d04 | non précisée (distribués via `npx skills add`) |
| `stripe-best-practices`, `stripe-docs`, `upgrade-stripe` | [stripe/ai](https://github.com/stripe/ai/tree/main/skills) (`providers/agent-plugins`) | 38fa045 | MIT |
| `resend`, `agent-email-inbox`, `email-best-practices` | [resend/resend-skills](https://github.com/resend/resend-skills) | 389de56 | MIT |
| `webapp-testing`, `frontend-design`, `mcp-builder`, `skill-creator` | [anthropics/skills](https://github.com/anthropics/skills) | 2c5958e | Apache 2.0 |
| `fastapi` | [fastapi/fastapi](https://github.com/fastapi/fastapi/tree/master/fastapi/.agents/skills/fastapi) (skill officiel) | 119bce9 | MIT |
| `brainstorming`, `writing-plans`, `executing-plans`, `subagent-driven-development`, `dispatching-parallel-agents`, `using-git-worktrees`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch` | [obra/superpowers](https://github.com/obra/superpowers) | 22f0b46 | MIT |
| `multi-agent-patterns`, `tool-design`, `harness-engineering`, `hosted-agents`, `long-horizon-prompting`, `memory-systems`, `evaluation`, `advanced-evaluation`, `context-fundamentals`, `context-degradation`, `context-optimization`, `context-compression`, `filesystem-context`, `project-development` | [muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) | 9ff0c99 | MIT |
| `accessibility`, `performance`, `core-web-vitals`, `best-practices`, `seo`, `web-quality-audit` | [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills) | afa8da9 | MIT |

Écartés : `gladia-using-cli` (installe la CLI via `curl | sh`, RunAI utilise le SDK/REST) ; de superpowers, `using-superpowers`, `diagnosing-superpowers` et `writing-skills` (méta-skills liés au plugin et à ses hooks, non copiés) ; de Context Engineering, les skills hors sujet pour RunAI (`latent-briefing`, `bdi-mental-states`, `self-managed-context`, `self-improvement-loops`, `book-sft-pipeline`, etc.).

Seule modification locale : la clé d'exemple `hk-…` de `hai-agents/references/portal/api-keys.md` est remplacée par `hk-EXAMPLE_KEY_REDACTED` (le test anti-secrets de `tests/test_repo.py` la détectait).

## Écarts connus avec RunAI

- Gladia : les skills recommandent le SDK, mais `gladiaio-sdk` 2.2.1 plante avec `audio_to_llm` (`KeyError: 'success'`) : passer par le REST (httpx) dans ce cas.
- H : `hai-agents/scripts/h_login.py` fait un login OAuth et écrit `HAI_API_KEY` dans `.env`. Sur Devin, utiliser plutôt le secret d'org `HAI_API_KEY`.
- Linkup : le skill conseille `deep` en cas de doute ; en pratique `deep` prend ~2 min contre ~5-10 s en `standard`.
