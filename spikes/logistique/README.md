# Spike logistique : le règlement d'une course via Linkup

Question : à partir d'un nom de course libre, Linkup trouve-t-il la page officielle et le règlement, et en sort-il une logistique fiable (modèle Pydantic) pour construire le week-end ?

## Ce qui est prouvé

- `extract.py` : `/search` structuré avec le schéma Pydantic `RaceLogistics` (`models.py`), `depth="standard"` puis `deep` si un champ critique manque (date, heure, lieu de départ, URL d'inscription). Variante `extract_race_fetch` : `standard` puis `/fetch` + schéma sur l'URL du règlement.
- `timeline.py` : timeline déterministe du week-end (départ, arrivée, retrait du dossard, hôtel, matin de course, arrivée estimée, check-out, retour) + export `.ics`. Chaque étape dérivée d'une hypothèse (trajet, allure, horaires par défaut) est marquée `assumption=True`.
- `find_open_races()` : liste de courses 2027 sur Njuko/Klikego (`includeDomains`).
- Testé sur 5 courses 2027 réelles (2 Klikego, 1 Njuko, 2 sites organisateurs). Détail champ par champ : [VERIFICATION.md](VERIFICATION.md).

## Résultats mesurés (7 nov. 2026)

| Mesure | Variante A (standard → deep) | Variante B (standard → fetch) |
| --- | --- | --- |
| Précision sur 4 champs × 5 courses | 13/16 = 81 % | 10/11 = 91 % |
| Champs remplis | 16/20 | 11/20 |
| Latence `standard` structuré | 4,5 à 9,4 s (n = 11) | idem |
| Latence 2e appel | `deep` : 108 à 124 s (n = 4) | `fetch` : 7,7 à 10 s (n = 4) |
| Coût liste par course | 0,006 $ ou 0,061 $ avec deep | 0,006 $ ou 0,012 $ |

- `deep` a été déclenché pour 4 courses sur 5 ; il a comblé les trous pour Royan et Lisbonne, pas pour Paris (1 appel `deep` « no result », non facturé).
- Le solde Linkup (`/v1/credits/balance`) est partagé avec d'autres agents qui tournaient en même temps : les deltas mesurés par appel (jusqu'à 0,43 $ pour un deep) ne sont pas attribuables. Les coûts ci-dessus sont les prix catalogue Linkup. Dépense totale de ce spike au prix catalogue : environ 0,33 $.
- Erreurs observées : jours de retrait incomplets (Lisbonne), lieu de départ déduit de l'adresse du siège (Paris). Conflit réel entre le site et le règlement de Lisbonne sur l'heure (09:20 contre 09h30).
- Courses ouvertes trouvées (Klikego, statut vérifié seulement pour Royan) : Marathon Royan Côte de Beauté (23/05/2027, marathon 65 €), Marathon des Sables d'Olonne (03-04/04/2027), Marathon de Chinon (04/04/2027), Semi Boucle de Seine (21/03/2027), 10 km et semi de Lorient (14/02/2027), 10 km des Champs-Élysées Fulfil (07/02/2027), Crevin, Vézère. Njuko : Connemara 2027, Forest Marathon 2027, Milan (04/04/2027). Liste brute : `results/open_races.json`.

## Relancer

```bash
.venv/bin/pip install -r requirements.txt
cd spikes/logistique
../../.venv/bin/pytest -q test_timeline.py          # timeline, sans réseau
../../.venv/bin/python extract.py "Marathon de Royan 2027"   # une course (LINKUP_API_KEY requis)
../../.venv/bin/python run_eval.py --force          # variante A sur les 5 courses
../../.venv/bin/python run_eval.py --fetch --force  # variante B
```

## Recommandation pour la démo

`standard` (≈ 6 s) affiché tout de suite, puis complément en tâche de fond (`fetch` du règlement ≈ 8 s, `deep` ≈ 2 min seulement hors chemin critique). Afficher les sources et marquer « à confirmer » tout champ vide ou en conflit. Pour la course de démo, pré-calculer et figer le JSON vérifié à la main.
