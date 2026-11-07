# RunAI

Projet du « Computer Use Agents Hackathon ». Le concept et le pitch restent à définir.

## Règles du hackathon

Le projet doit utiliser au moins **3 partenaires** parmi Devin, H Company, Gladia, Linkup et Stripe.
Le trio prévu est **Devin + H Company + Gladia** ; Linkup pourra être ajouté comme quatrième partenaire.

| Partenaire | Rôle | Utilisé ? | Documentation |
| --- | --- | --- | --- |
| Devin | Assistance au développement | Prévu | [Guide du hackathon](Infos/devin_hackathon_guide.pdf) |
| H Company | Agents de navigation et d’automatisation | Script de test présent ; intégration prévue | [API Agents](https://hub.hcompany.ai/agents-api/overview) |
| Gladia | Transcription audio et traitement de la parole | Prévu | [Documentation](https://docs.gladia.io) |
| Linkup | Recherche web pour les agents | Optionnel, quatrième partenaire possible | [Documentation](https://docs.linkup.so/pages/documentation/get-started/introduction) |
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

## Tester

Depuis la racine du dépôt, avec l’environnement virtuel activé et une clé H valide dans `.env` :

```bash
python scripts/test_h.py
```

Ce test appelle réellement l’API H, nécessite une connexion réseau et peut consommer des crédits.
Il demande à l’agent de trouver l’article principal de Hacker News, puis affiche son statut et sa réponse.

## Structure du repo

```text
RunAI/
├── Infos/              # Guides partenaires et récapitulatif des crédits
├── scripts/
│   └── test_h.py       # Test de l’API H
├── .env.example        # Variables d’environnement à renseigner
├── .gitignore
├── README.md
└── requirements.txt    # Dépendances Python et interface de commande Holo
```

## Équipe

À compléter : membres, rôles et coordonnées utiles.
