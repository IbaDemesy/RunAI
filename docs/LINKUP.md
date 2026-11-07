# Linkup pour RunAI

Ce qu'il faut savoir sur Linkup pour l'intégrer à RunAI. Rôle dans l'architecture : **Linkup cherche, H agit**. Linkup est branché comme **outil d'un agent H** (et non de Devin) : l'agent H l'appelle pour trouver la course, l'hôtel ou le transport, puis va remplir le formulaire choisi.

## Liens

- [Introduction](https://docs.linkup.so/pages/documentation/get-started/introduction), [démarrage rapide](https://docs.linkup.so/pages/documentation/get-started/quickstart), [index complet pour agents (llms.txt)](https://docs.linkup.so/llms.txt)
- [Search](https://docs.linkup.so/pages/documentation/endpoints/search/overview), [bonnes pratiques Search](https://docs.linkup.so/pages/documentation/endpoints/search/best-practices), [sortie structurée](https://docs.linkup.so/pages/documentation/tutorials/structured-output-guide), [filtrage des sources](https://docs.linkup.so/pages/documentation/tutorials/filtering)
- [Fetch](https://docs.linkup.so/pages/documentation/endpoints/fetch/overview), [SDK Python](https://docs.linkup.so/pages/sdk/python/python), [serveur MCP](https://docs.linkup.so/pages/integrations/mcp/mcp)
- [Tableau de bord et clé API](https://app.linkup.so), [playground](https://app.linkup.so/playground)
- Crédits du hackathon et doc PDF : voir [Infos/README.md](../Infos/README.md#linkup)

## Les endpoints utiles pour nous

| Endpoint | Ce qu'il fait | Usage RunAI |
| --- | --- | --- |
| `/search` | Recherche web, renvoie des sources, une réponse sourcée ou du JSON selon notre schéma | Trouver la course (date, distance, lieu du départ, URL d'inscription), les hôtels proches du départ, les trains ou vols |
| `/fetch` | Lit une URL connue et la rend en markdown, avec en option un JSON typé (`schema`) | Lire la page d'une course pour extraire prix, distances, date limite, PPS ou certificat requis |
| `/research` | Recherche longue et asynchrone (0,25 à 2,50 $ par appel) | Trop lent et cher pour la démo, à éviter |

### `/search` : profondeur (`depth`)

| `depth` | Latence | Quand l'utiliser |
| --- | --- | --- |
| `flash` (alpha) | < 200 ms | Mots-clés seulement, pas de LLM |
| `fast` | ~1 s | Mots-clés seulement, meilleur classement |
| `standard` | 1–3 s | Requête en langage naturel, peut lire **une** URL donnée dans la requête. **Choix par défaut pour RunAI.** |
| `deep` | 5–30 s | Trouver une URL puis la lire, ou lire plusieurs URL. Pour la page d'inscription si `standard` ne suffit pas. |

`flash` et `fast` prennent les consignes pour des mots-clés : pour « trouve le semi de Lisbonne en mars et son lien d'inscription », il faut `standard` ou `deep`.

### `/search` : type de sortie (`outputType`)

- `searchResults` : liste `{name, url, content}`.
- `sourcedAnswer` : réponse en texte avec citations.
- `structured` : JSON conforme à `structuredOutputSchema` (racine de type `object`). **C'est ce qu'il nous faut** : l'orchestrateur reçoit des champs typés, pas du texte à parser. La requête doit demander explicitement les infos du schéma.

Filtres : `includeDomains` / `excludeDomains` (jusqu'à 100 domaines, par exemple `njuko.net`, `klikego.com`), `fromDate` / `toDate`, `maxResults`.

### `/fetch` : points d'attention

- Mettre `renderJs: true` par défaut : beaucoup de sites d'inscription sont rendus côté client.
- Avec un `schema`, les champs introuvables sur la page sont **omis, jamais inventés**. C'est cohérent avec notre règle « ne pas inventer les données manquantes ».
- Pas d'authentification : une page derrière un login renvoie ce qu'un visiteur anonyme voit. Ce sera l'agent H qui gère les comptes.
- Ne suit pas les liens : une URL par appel.

## Coûts et limites

| Appel | Coût |
| --- | --- |
| `/search` `standard` + `structured` | 0,006 $ |
| `/search` `deep` + `structured` | 0,055 $ |
| `/fetch` `standard`, `renderJs` | 0,005 $ (+0,001 $ avec `schema`) |

- 20 $ offerts à l'inscription avec un e-mail pro, plus l'offre du hackathon (voir [Infos/README.md](../Infos/README.md#linkup)). Une démo complète coûte quelques centimes.
- Aucun crédit débité en cas d'erreur ou de résultat vide.
- Limite : 10 requêtes par seconde par organisation. Crédit épuisé : erreur `429`.

## Brancher Linkup sur un agent H

Le SDK H (`hai-agents`) accepte des fonctions Python comme [outils personnalisés](https://hub.hcompany.ai/agents-api/custom-tools) : le schéma est déduit de la signature et de la docstring, et l'agent les appelle quand il en a besoin. Les outils ne tournent que tant que notre programme attend la session.

```python
from hai_agents import Client
from linkup import LinkupClient  # pip install linkup-sdk ; lit LINKUP_API_KEY

linkup = LinkupClient()

RACE_SCHEMA = """{
  "type": "object",
  "properties": {
    "races": {"type": "array", "items": {"type": "object", "properties": {
      "name": {"type": "string"},
      "date": {"type": "string", "description": "ISO 8601"},
      "distance_km": {"type": "number"},
      "start_location": {"type": "string"},
      "registration_url": {"type": "string"},
      "price_eur": {"type": "number"}
    }}}
  }
}"""

def search_races(query: str) -> str:
    """Cherche des courses à pied (date, distance, départ, URL d'inscription, prix)."""
    response = linkup.search(
        query=query,
        depth="standard",
        output_type="structured",
        structured_output_schema=RACE_SCHEMA,
    )
    return str(response)

client = Client()
result = client.run_session(
    agent="h/web-surfer-pro",
    messages=(
        "Trouve le semi-marathon de Lisbonne en mars avec search_races, "
        "ouvre la page d'inscription et remplis le formulaire avec le profil fourni. "
        "Arrête-toi avant le paiement."
    ),
    tools=[search_races],
)
print(result.answer)
```

Exemple non testé, à valider avec nos clés. Points à garder en tête :

- Exécution « au moins une fois » : un outil peut être rappelé si l'envoi du résultat échoue. Les outils Linkup sont en lecture seule, donc sans risque.
- Une exception dans l'outil remonte à l'agent comme erreur d'outil, sans faire planter la session.
- Variante possible : appeler Linkup dans l'orchestrateur avant de lancer l'agent H, puis lui donner directement l'URL choisie. C'est plus déterministe et plus rapide, mais moins « agent ». Garder les deux options et trancher au premier test.
- Un dossard ou un hôtel trouvé par Linkup reste une **proposition** : la validation (bonne course, bonne distance, prix plafond) se fait côté serveur, voir [FEATURES_A_REPRENDRE.md](FEATURES_A_REPRENDRE.md).
