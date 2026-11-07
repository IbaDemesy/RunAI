# Devis d'inscription et coût du week-end (`runai/quote/`)

Lit le prix réel d'une inscription **sans navigateur ni session H**, le combine avec l'hôtel et le transport, et contrôle les prix rapportés par les agents H. Lecture seule : aucun panier, compte ni formulaire.

## API

```python
from runai.quote import fetch_njuko_quote, weekend_cost, verifier_devis, verifier_prix

devis = fetch_njuko_quote("https://in.njuko.com/wizz-air-milano-marathon-20271776152378557", "non comp")
devis.palier_actuel            # Palier(prix_eur=114.0, date_fin=2026-12-31)
devis.paliers_suivants         # 124 € (28/02/2027), 131 € (03/04/2027)
devis.places_restantes, devis.options, devis.frais_service_eur

cout = weekend_cost(devis, ["assurance d'annulation", "t-shirt blanc"], hotel_eur=94, transport_eur=150)
cout.lignes, cout.total_eur, cout.total_par_source   # {"mesure": 149, "estime": 244}

verifier_prix(step.price_eur, devis).ok      # prix vu au panier par l'agent H inscription
verifier_devis(devis_agent, source=devis)    # Devis complet renvoyé par un agent H
```

| Fonction | Rôle |
| --- | --- |
| `fetch_njuko_quote(url_or_slug, epreuve=None)` → `Devis` | API publique `front-api.njuko.com` : `edition/url/{slug}`, `prices-for-competition/{id}` (paliers datés), `competition/remaining/{id}` (places, POST vide comme la page), `fields/{edition}` (options payantes). 4 requêtes, ~2,7 s. `epreuve` : sous-chaîne du nom (toutes langues) ; sans filtre, 1re épreuve + avertissement. |
| `fetch_njuko_quotes(...)` → `list[Devis]` | Une entrée par épreuve visible. |
| `fetch_klikego_quote(url, epreuve=None)` | Page événement + fiche épreuve publiques (2 GET) : droit d'inscription, tarif dernière minute, frais de gestion, options trouvées dans la description (indicatif). |
| `fetch_quote(url, epreuve)` | Aiguille Njuko / Klikego selon l'URL. |
| `weekend_cost(devis, options_choisies, hotel_eur, transport_eur)` → `CoutWeekend` | Lignes inscription + frais hors prix + options obligatoires et choisies (id, nom ou sous-chaîne unique) + hôtel + transport, chacune avec sa source `mesure` / `agent` / `estime`. `None` = non chiffré (avertissement). |
| `verifier_prix(prix, devis, options_choisies)` → `VerificationDevis` | Compare un prix rapporté à l'attendu ; signale s'il correspond à un autre palier. |
| `verifier_devis(devis, source=None)` → `VerificationDevis` | Cohérence interne (total, `rien_soumis`, dates) et, avec `source`, palier, frais, options, complet. `ok` = aucun écart bloquant. |
| `devis_answer_schema()` | JSON Schema de `Devis` pour un futur agent H « devis » (`answer_schema`). |

Tous les `fetch_*` acceptent `client=httpx.Client(...)` (tests : `httpx.MockTransport`) et `now=` (palier courant calculé à cette date, dates de fin en heure locale de la course).

Relevé en ligne de commande :

```bash
.venv/bin/python -m runai.quote wizz-air-milano-marathon-20271776152378557 "non comp" --option "assurance d'annulation" --hotel 94 --transport 150
```

## Limites

- **Frais Njuko** : le montant (5 € à Milan) est cherché dans les textes du formulaire ; l'API ne dit pas s'il est inclus. `frais_inclus_dans_prix=None` : non compté dans le total, avertissement, et `verifier_prix` accepte le prix avec ou sans frais.
- **Options obligatoires** : selon le drapeau `required` de Njuko. À Milan l'option « tourisme sportif » (5 €) n'est pas marquée obligatoire alors qu'elle conditionne l'inscription non compétitive : à confirmer au panier.
- Prix d'option = prix minimal parmi ses variantes (tailles).
- Klikego : extraction par motifs sur le HTML, fragile ; date de bascule « dernière minute » non affichée. Jamais au-delà de la fiche (« S'inscrire » crée un compte, CGU anti-robots).
- Pas de cache : un appel = un relevé daté (`releve_le`). Aucune charge : appeler à la demande, pas en boucle.
