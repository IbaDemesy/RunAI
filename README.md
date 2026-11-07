# RunAI

Projet du « Computer Use Agents Hackathon » (H Company × 42AI, 7–8 novembre 2026).

**« Dis-moi ta course, je prépare tout le déplacement. »** Le coureur dit à voix haute la course qu'il veut faire. RunAI trouve la page officielle avec Linkup, puis des agents H préparent en parallèle l'inscription, l'hôtel et le transport sur les vrais sites, et s'arrêtent avant tout paiement ou engagement.

## Avancement

- [Notation du jury : ce qui est fait, ce qui manque](docs/NOTATION.md)
- [Démo et livrables](docs/DEMO_ET_LIVRABLES.md)
- [Recherches des agents : ce qu'on fait, en option, coupé](docs/RECHERCHES_AGENTS.md)

## Règles du hackathon

Le projet doit utiliser au moins **3 partenaires** parmi Devin, H Company, Gladia, Linkup et Stripe.
RunAI en utilise **4** : Devin, H Company, Gladia et Linkup.

| Partenaire | Rôle | Utilisé ? | Documentation |
| --- | --- | --- | --- |
| Devin | Développement, exploration multi-agents, CI | Utilisé : PR, CI, workflow de 16 agents | [Guide du hackathon](Infos/devin_hackathon_guide.pdf) |
| H Company | Agents de navigation et d’automatisation | Testé : 3 agents en parallèle, smoke test ; intégration prévue | [API Agents](https://hub.hcompany.ai/agents-api/overview) |
| Gladia | Transcription audio et traitement de la parole | Testé : smoke test sur chaque push ; interface vocale prévue | [Documentation](https://docs.gladia.io) |
| Linkup | Recherche web, branchée comme outil des agents H | Testé : smoke test sur chaque push ; architecture « Linkup cherche, H agit » | [Documentation](https://docs.linkup.so/pages/documentation/get-started/introduction), [notes RunAI](docs/LINKUP.md) |
| Stripe | Paiements | Non prévu pour le moment | [Ressource du hackathon](Infos/stripe_credits.pdf) |

Les liens utiles, documents et crédits sont regroupés dans [Infos/README.md](Infos/README.md).

## Installation

Depuis la racine du dépôt, avec Python installé :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
2. Sur la [page de facturation](https://app.gladia.io/billing), appliquez le code promo indiqué dans [le PDF des crédits](Infos/gladia_hackathon_credits.pdf) pour obtenir les 1 000 crédits du hackathon.
3. Renseignez `GLADIA_API_KEY` dans `.env`.

Le SDK Python `gladiaio-sdk` est installé via `requirements.txt` et lit automatiquement `GLADIA_API_KEY`.

Optionnel, pour donner à un agent de code (Claude Code, Cursor, Codex) le contexte Gladia :

```bash
npx skills add gladiaio/skills
claude mcp add gladia --env GLADIA_API_KEY=... -- npx -y @gladiaio/mcp
```

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

Tests hors ligne (sans clé) : `ruff check .` puis `pytest -q`.

## CI/CD

Le workflow `ci.yml` s’exécute sur chaque pull request et sur les pushs vers `main` : il vérifie le style avec Ruff et lance les tests hors ligne avec `pytest`.

Le workflow `smoke.yml` lance les tests réels Linkup et Gladia lors d’un push vers `main`. Chaque test est ignoré avec une notice si son secret n’est pas configuré. Le test H est manuel : dans **Actions → Smoke → Run workflow**, activez `run_h=true`. Il prend environ 3 minutes et consomme des crédits ; le forfait H Free autorise 3 sessions concurrentes.

Secrets de dépôt requis : `HAI_API_KEY`, `LINKUP_API_KEY`, `GLADIA_API_KEY`.

Les workflows installent les dépendances avec `uv` ; en local, utilisez `uv venv && uv pip install -r requirements.txt ruff pytest`.

Le déploiement continu vers Render sera ajouté avec le backend.

## Structure du repo

```text
RunAI/
├── .github/workflows/  # CI (ci.yml) et smoke tests (smoke.yml)
├── Infos/              # Guides partenaires et récapitulatif des crédits
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
