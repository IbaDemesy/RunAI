# Spike boucle_devin : skill H versionné, corrigé puis relancé

Ce qui est prouvé (mesuré le 07/11/2026, clé H de l'org RunAI, région EU) :

1. **Échec voulu, faute d'instruction.** Le skill `runai-books-runbook` révision 1 limite l'agent au catalogue de
   books.toscrape.com (site bac à sable stable). La fiche produit, seule page qui affiche l'UPC et le stock, n'y figure pas.
   L'agent `runai-boucle-books` (holo4-27b, `h/browser`) répond `status=bloque`, `upc=null`, `stock=null`.
2. **Trace d'échec.** `boucle.py trace` lit les événements H (`GET /sessions/{id}/events`) : pensées, actions, URL,
   erreurs de validation, coût, dernière capture. Il en fait un prompt de réparation (`results/run1_echec_repair_prompt.md`).
3. **Réparation.** `devin_repair.py` crée une session Devin (API v3, `structured_output_schema` = nouveau corps du skill)
   si `DEVIN_API_KEY` et `DEVIN_ORG_ID` existent. **Ici ils n'existent pas : l'étape est simulée.** Le correctif
   `skills/books_runbook_v2.md` a été écrit à la main par une session Devin à partir du prompt.
4. **Nouvelle révision + relance.** `PUT /api/v2/skills/runai-books-runbook?message=...` crée la révision 2. L'agent
   référence le skill sans `:N`, donc la relance prend la révision 2 (`dependency_revisions` le confirme) et réussit.

## Résultats mesurés

| Étape | Session H | Révision du skill | Durée | Coût H | Résultat |
|---|---|---|---|---|---|
| Run 1 | `f492f820-5161-4509-a3d1-c49d83e94a72` | 1 | 39,4 s, 4 étapes | 0,0159 $ | échec : upc/stock null, `bloque` |
| Trace + prompt | - | - | 2 s | - | 21 événements, 1 capture |
| Mise à jour du skill | - | 1 → 2 | 1 s | - | ETag `"2"`, message de révision |
| Run 2 | `12157957-c6b5-4b70-9e9d-7ffe70303d1d` | 2 | 28,6 s, 4 étapes | 0,0096 $ | succès : UPC `a897fe39b1053632`, stock 22 |

- Boucle totale, du début du run 1 à la fin du run 2 : **126 s** (`results/report.json`). Somme des étapes
  automatiques : 75 s. Les ~50 s restantes sont le temps de lecture de la trace et d'écriture du correctif à la main.
  Une vraie session Devin prendrait plus longtemps : non mesuré.
- 2 runs H sur 3 autorisés. Les deux sessions ont été annulées (`DELETE` → 204) à la fin.
- Au run 1, l'agent a d'abord envoyé `status="bloqué"` (avec accent), refusé par le schéma, puis `bloque`. La v2
  l'indique explicitement.
- Le run 1 a été retracé une fois après une correction du parseur de trace : l'étape `trace` du journal date de 15:09.
- Vérité terrain lue par le script sur la fiche produit (`validate()`), pas par l'agent.

## Relancer

```bash
cd spikes/boucle_devin   # HAI_API_KEY dans l'environnement
P=../../.venv/bin/python
$P boucle.py setup              # skill v1 + agent (remet le skill en v1 -> nouvelle révision)
$P boucle.py run run1_echec     # attend un slot H (10 min max), annule la session à la fin
$P boucle.py trace run1_echec   # trace + prompt de réparation
$P boucle.py repair run1_echec  # API Devin si DEVIN_API_KEY + DEVIN_ORG_ID, sinon skills/books_runbook_v2.md
$P boucle.py update             # nouvelle révision du skill
$P boucle.py run run2_relance
$P boucle.py report
```

Le skill et l'agent restent dans le catalogue H de l'org (ils n'occupent aucun slot de session).

## Pour la brancher en vrai

- **Clé Devin** : un service user (jeton `cog_...`) avec la permission de créer des sessions dans l'org, plus l'id de l'org
  (`DEVIN_ORG_ID`). Variables `DEVIN_API_KEY` et `DEVIN_ORG_ID` côté backend uniquement. `DEVIN_MAX_ACU` (3 par défaut)
  limite le coût de chaque réparation.
- **Repo** : l'intégration GitHub de l'org Devin doit avoir accès en écriture à `IbaDemesy/RunAI` pour que la session
  ouvre une PR sur `spikes/boucle_devin/skills/` (le prompt la demande).
- **Session de réparation** : elle a besoin de `HAI_API_KEY` (secret d'org) pour relancer elle-même un test H, et d'un
  slot H libre. Les slots sont partagés avec la démo à 3 agents.
- **Garde-fou** : en production, ne pas appliquer le skill rendu par Devin directement. Le faire valider (PR mergée ou
  clic humain), puis faire le `PUT`. Le `If-Match` sur l'ETag évite d'écraser une révision concurrente. Pour revenir en
  arrière : `POST /skills/{name}/revisions/1/restore`.
