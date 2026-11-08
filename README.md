# RunAI

Projet du « Computer Use Agents Hackathon » (H Company × 42AI, 7–8 novembre 2026).

**« Dis-moi ta course, je prépare tout le déplacement. »** Le coureur dit à voix haute la course qu'il veut faire. RunAI trouve la page officielle avec Linkup, puis des agents H préparent en parallèle l'inscription, l'hôtel et le transport sur les vrais sites, et s'arrêtent avant tout paiement ou engagement.

## Avancement

- [Plan de développement multi-agents — équipes, lots et voyage complet](docs/PLAN_DEVELOPPEMENT.md)
- [Frontend — direction visuelle, écrans et critères de finition](docs/FRONTEND.md)
- [Notation du jury : ce qui est fait, ce qui manque](docs/NOTATION.md)
- [Démo et livrables](docs/DEMO_ET_LIVRABLES.md)
- [Recherches des agents : ce qu'on fait, en option, coupé](docs/RECHERCHES_AGENTS.md)

## Règles du hackathon

Le projet doit utiliser au moins **3 partenaires** parmi Devin, H Company, Gladia, Linkup et Stripe.
RunAI en utilise **4** : Devin, H Company, Gladia et Linkup.

| Partenaire | Rôle | Utilisé ? | Documentation |
| --- | --- | --- | --- |
| Devin | Développement, exploration multi-agents, CI | Utilisé : PR, CI, workflow de 16 agents | [Devin docs](https://docs.devin.ai) |
| H Company | Agents de navigation et d’automatisation | Câblé en V2 via lifecycle ; recette intégrée live restant à faire | [API Agents](https://hub.hcompany.ai/agents-api/overview) |
| Gladia | Transcription audio, sans TTS | Câblé au shell vocal ; smoke tests conditionnels | [Documentation](https://docs.gladia.io) |
| Linkup | Recherche de candidats et fiche course sourcée | Câblé au cadrage V2 ; smoke tests conditionnels | [Documentation](https://docs.linkup.so/pages/documentation/get-started/introduction), [notes RunAI](docs/LINKUP.md) |
| Stripe | Paiements | Non prévu pour le moment | [Hackathon offer](https://stripe.com/startup-benefits/computer-use-agents-hackathon) |

Les liens utiles, documents et crédits sont regroupés dans [Infos/README.md](Infos/README.md).

## V2 : préparer une course

Le parcours est **cadrage → confirmation explicite → agents → JourneyPlan → exports**.
Décrivez la course et le déplacement, précisez les informations manquantes et choisissez
un candidat sourcé. Vérifiez le résumé avant confirmation : aucun agent ne démarre avant.
Seules les étapes couvertes sont lancées ; leurs résultats enrichissent le même séjour
révisé pour la carte, la timeline accessible et les exports HTML/PDF/ICS.

Choisissez explicitement `RUNAI_MODE` :

| Mode | Comportement |
| --- | --- |
| `live` | Linkup, H et Gladia réels selon les clés/SDK disponibles. Un fournisseur sans clé produit un état indisponible et une erreur honnête, jamais un repli silencieux en démo. |
| `demo` | Candidats de fixtures et agents/transcription simulés, étiquetés démo. Ville ou critères sans fixture : limitation explicite, aucun événement de remplacement inventé. |
| `replay` | Trace `replay.v1` explicite via `RUNAI_REPLAY_TRACE`, sans appel fournisseur ; données marquées replay. Sans trace, le démarrage est refusé. |

Variables de clés, **noms seulement** : `HAI_API_KEY`, puis `HAI_API_KEY_2`,
`HAI_API_KEY_3`, etc. sans trou dans la numérotation ; `LINKUP_API_KEY` ;
`GLADIA_API_KEY`. **Linkup ne lit que `LINKUP_API_KEY`**, pas ses variantes numérotées.
Ne versionnez jamais les valeurs ni `.env`.

Après l'installation ci-dessous, choisissez une commande depuis la racine :

```bash
RUNAI_MODE=demo .venv/bin/python -m runai.app
# Ou, avec les fournisseurs configurés :
RUNAI_MODE=live .venv/bin/python -m runai.app
# Ou, avec votre trace existante :
RUNAI_MODE=replay RUNAI_REPLAY_TRACE=/chemin/trace.json .venv/bin/python -m runai.app
```

Ouvrez `http://127.0.0.1:8000`. Hôte et port sont réglables avec `RUNAI_APP_HOST`
et `RUNAI_APP_PORT`. [Commandes de test hors ligne](#tester) et [détails techniques V2](docs/V2.md).

**Limites actuelles :** stockage mémoire des cadrages, missions, idempotence, événements
SSE et révisions d'export ; automatisation limitée à **Njuko / Accor / Trenitalia**
(train et couverture Italie pour ce dernier). Les autres plateformes/transports sont
manuels, avec lien officiel lorsqu'il est connu ; Booking.com et TAP sont exclus de
l'automatisation. L'extraction FR/EN est heuristique et partielle : corrigez les champs
dans le cadrage. Le profil utilisé par défaut est fictif. Aucun paiement, réservation,
compte, consentement, déclaration de santé ou soumission engageante n'est automatisé.
Gladia sert à transcrire, **pas à faire de la synthèse vocale (TTS)**. Les données
Journey non fournies de façon structurée restent inconnues ; les traces JSONL peuvent
être écrites sur disque, mais ne constituent pas un stockage persistant des missions.

## Installation

Depuis la racine du dépôt, avec Python installé :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Renseignez les clés nécessaires dans `.env` : `HAI_API_KEY`, `GLADIA_API_KEY` et `LINKUP_API_KEY`.
Ne publiez jamais ce fichier ni vos clés.

### Installation des agents H

Dans un environnement virtuel Python activé :

```bash
pip install -r requirements.txt
holo login
holo mcp install vscode
```

`holo login` ouvre une connexion navigateur ou permet de se connecter avec une clé API H. La commande MCP ajoute Holo aux serveurs MCP de l'utilisateur dans VS Code ; après avoir créé l'environnement virtuel du dépôt, relancez-la si nécessaire pour pointer vers son exécutable `holo`.

### Installation de Gladia

1. Créez un compte et une clé API sur [app.gladia.io](https://app.gladia.io/apikeys).
2. Sur la [page de facturation](https://app.gladia.io/billing), apply the hackathon promo code (kept privately by the team) to get the 1,000 hackathon credits.
3. Renseignez `GLADIA_API_KEY` dans `.env`.

Le SDK Python `gladiaio-sdk` est installé via `requirements.txt` et lit automatiquement `GLADIA_API_KEY`.

Optionnel, pour donner à un agent de code (Claude Code, Cursor, Codex) le contexte Gladia :

```bash
npx skills add gladiaio/skills
```

Pour le serveur MCP Gladia, configurez `GLADIA_API_KEY` dans son environnement,
sans consigner sa valeur dans un fichier versionné.

## Tester

Depuis la racine du dépôt, avec l’environnement virtuel activé et une clé H valide dans `.env` :

```bash
python scripts/test_h.py
```

Ce test appelle réellement l’API H, nécessite une connexion réseau et peut consommer des crédits.
Il demande à l’agent de trouver l’article principal de Hacker News, puis affiche son statut et sa réponse.

Pour Gladia, avec une clé valide dans `.env` :

```bash
python scripts/test_gladia.py                 # fichier audio d’exemple de Gladia
python scripts/test_gladia.py mon_audio.mp3   # fichier local ou URL
```

Ce test appelle réellement l’API Gladia et consomme des crédits. Il transcrit l’audio, puis affiche le statut et la transcription.

Pour Linkup, avec une clé valide dans `.env` :

```bash
python scripts/test_linkup.py
```

Ce test lance une vraie recherche et affiche le nombre de résultats et la première URL.

Tests hors ligne (sans clé), avec les dépendances installées dans `.venv` :

```bash
source ~/.nvm/nvm.sh  # sur la VM : Node 24 doit aussi être dans le PATH de pytest
.venv/bin/ruff check .
.venv/bin/pytest -q
node --test web/flyover/tests/*.test.js tests/contracts/*.test.js runai/app/static/tests/*.test.js web/voice/tests/*.test.js
for script in runai/app/static/*.js web/flyover/*.js web/voice/voice-input.js; do node --check "$script" || break; done
```

Les tests UX rejouent les patches D1 sur le commit `97265c6` ; un clone de test doit
contenir cet historique. Le job CI utilise un checkout complet et installe Node 24
avant pytest et les suites JavaScript.

## CI/CD

Le workflow `ci.yml` s’exécute sur chaque pull request et sur les pushs vers `main` : il vérifie le style avec Ruff et lance les tests hors ligne avec `pytest`.

Le workflow `smoke.yml` lance les tests réels Linkup et Gladia lors d’un push vers `main` qui modifie `scripts/`, `requirements.txt` ou `smoke.yml`, pour ne pas consommer de crédits sur les PR de documentation. On peut aussi le lancer à la main (**Actions → Smoke → Run workflow**). Chaque test est ignoré avec une notice si son secret n’est pas configuré. Le test H est manuel : dans **Actions → Smoke → Run workflow**, activez `run_h=true`. Il prend environ 3 minutes et consomme des crédits ; le forfait H Free autorise 3 sessions concurrentes.

Secrets de dépôt requis : `HAI_API_KEY`, `LINKUP_API_KEY`, `GLADIA_API_KEY`.

Les workflows installent les dépendances avec `uv` ; en local, utilisez `uv venv && uv pip install -r requirements.txt -r requirements-dev.txt`.

## Hosting on Render

Deploy the repository with the `render.yaml` Blueprint. Keep a single instance:
missions and authentication failure counters live in process memory and reset on
restart. `/api/health` is the only public route when authentication is enabled;
static assets, `/demo/live`, event streams and screenshots require credentials.

Set `RUNAI_BASIC_AUTH=user:password` in Render's secret environment settings.
For separate credentials, use a comma-separated list such as
`user:password,user2:password2` (commas cannot be part of a password).
After five failed authentication attempts within 60 seconds, that client IP is
blocked with HTTP 429 and a `Retry-After` header until the window expires.
The first `X-Forwarded-For` hop identifies clients behind Render's TLS proxy;
use this deployment only behind a trusted proxy that supplies that header.

Security headers apply to authenticated and rejected responses alike, and API
responses use `Cache-Control: no-store`. Content Security Policy defaults to
`Content-Security-Policy-Report-Only` (`RUNAI_CSP_ENFORCE=0`) so violations can
be reviewed in the browser console without blocking resources. Set
`RUNAI_CSP_ENFORCE=1` to send enforcing `Content-Security-Policy` instead.

## Structure du repo

```text
RunAI/
├── .github/workflows/  # CI (ci.yml) et smoke tests (smoke.yml)
├── Infos/              # Public partner documentation links
├── docs/               # Notation, démo, recherches, notes partenaires
├── scripts/
│   ├── test_gladia.py  # Test de l’API Gladia
│   ├── test_h.py       # Test de l’API H
│   └── test_linkup.py  # Test de l’API Linkup
├── tests/              # Tests hors ligne (imports, .env.example, clés committées)
├── .env.example        # Variables d’environnement à renseigner
├── .gitignore
├── README.md
└── requirements.txt    # Dépendances Python, SDK Gladia et interface de commande Holo
```

## Équipe

À compléter : membres, rôles et coordonnées utiles.
