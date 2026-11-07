# RunAI-

## Installation des agents H

Dans un environnement virtuel Python activé :

```bash
pip install -r requirements.txt
holo login
holo mcp install vscode
```

`holo login` ouvre une connexion navigateur ou permet de se connecter avec une clé API H. La commande MCP ajoute Holo aux serveurs MCP de l'utilisateur dans VS Code ; après avoir créé l'environnement virtuel du dépôt, relancez-la si nécessaire pour pointer vers son exécutable `holo`.

## Tests

Lancez les tests unitaires avec :

```bash
python -m unittest discover -s tests -v
```

Cette commande est exécutée automatiquement par GitHub Actions pour chaque pull request.