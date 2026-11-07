# Skills Devin

Skills officiels des éditeurs du stack RunAI, copiés tels quels (format `SKILL.md`, chargés automatiquement par Devin depuis `.devin/skills/`). Ne pas les modifier ici : les mettre à jour depuis leur source.

| Skills | Source | Commit | Licence |
|---|---|---|---|
| `hai-agents`, `hai-qa-via-cli` | [hcompai/computer-use-agents-demos](https://github.com/hcompai/computer-use-agents-demos/tree/main/skills) | fd9e283 | MIT |
| `gladia-*` (6) | [gladiaio/skills](https://github.com/gladiaio/skills) | 3355562 | MIT |
| `linkup-*` (5) | [LinkupPlatform/skills](https://github.com/LinkupPlatform/skills) | dfc1d04 | non précisée (distribués via `npx skills add`) |
| `stripe-best-practices`, `stripe-docs`, `upgrade-stripe` | [stripe/ai](https://github.com/stripe/ai/tree/main/skills) (`providers/agent-plugins`) | 38fa045 | MIT |
| `resend`, `agent-email-inbox`, `email-best-practices` | [resend/resend-skills](https://github.com/resend/resend-skills) | 389de56 | MIT |
| `webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills) | 2c5958e | Apache 2.0 |

Écartés : `gladia-using-cli` (installe la CLI via `curl | sh`, RunAI utilise le SDK/REST).

## Écarts connus avec RunAI

- Gladia : les skills recommandent le SDK, mais `gladiaio-sdk` 2.2.1 plante avec `audio_to_llm` (`KeyError: 'success'`) : passer par le REST (httpx) dans ce cas.
- H : `hai-agents/scripts/h_login.py` fait un login OAuth et écrit `HAI_API_KEY` dans `.env`. Sur Devin, utiliser plutôt le secret d'org `HAI_API_KEY`.
- Linkup : le skill conseille `deep` en cas de doute ; en pratique `deep` prend ~2 min contre ~5-10 s en `standard`.
