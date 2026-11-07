# Spike survol — survol 3D du week-end et insights de parcours

## Ce qui est prouvé
- **Un agent H « éclaireur » récupère le tracé d'une vraie course 2027** depuis sa page officielle et le transmet à RunAI sous forme de **fichier**. Il télécharge le fichier dans `~/Downloads` de son navigateur cloud et appelle l'outil client `trace_telecharge`. Le script liste alors le dossier avec `session_files.list_files`, lit le fichier avec `read_file` (Base64), puis l'enregistre dans `data/`.
- **Page statique** `index.html` : MapLibre GL 5.6, satellite Esri ou OSM, relief 3D Mapterhorn (Terrarium, sans clé). La caméra va de la gare/l'aéroport à l'hôtel, puis au retrait des dossards, à l'hôtel et au départ. Elle suit ensuite tout le parcours, avec les bornes km, les ravitaillements, l'altitude et l'allure en direct, jusqu'à l'arrivée.
- **Insights calculés localement** (`build_insights.py`) :
  - KML/GPX rééchantillonné tous les 25 m ;
  - altitude échantillonnée dans les tuiles Terrarium ;
  - **correction ponts/tunnels** : on détecte un saut de plus de 12 % puis une sortie dont la corde passe au-dessus ou au-dessous d'au moins 10 m, avec une pente de corde d'au plus 6 % ; on lisse ensuite sur 150 m et on applique une hystérésis de 1 m pour le D+ ;
  - côtes, ravitaillements (repères du tracé ou réponse de H) et allure km par km pour un objectif donné ;
  - trajets du week-end calculés avec OSRM.
- **Fallback sans tracé** (`--fallback`) : départ, arrivée et trajets hôtel → retrait et hôtel → départ.

## Relancer
```bash
cd spikes/survol
HAI_API_KEY=... ../../.venv/bin/python eclaireur_h.py lisbonne   # ou milan ; vérifie le quota, annule toujours la session
../../.venv/bin/python build_insights.py data/trace_h_lisbonne_2026.kml --h-run data/h_run_lisbonne_562119bf.json
../../.venv/bin/python build_insights.py data/trace_h_wizz-air-milano-marathon-2026-milano-2026-track.gpx \
  --h-run data/h_run_milan_9ff8cf08.json --ville milan --objectif 3:45:00 --out data/course_milan.json
../../.venv/bin/python build_insights.py --fallback --out data/course_fallback.json
python3 -m http.server 8765 --bind 127.0.0.1   # puis http://127.0.0.1:8765/index.html?data=data/course_milan.json  (&terrain=0 pour couper la 3D)
../../.venv/bin/python mesure_rendu.py data/course.json --play [--sans-terrain]   # Playwright via le CDP de Chrome (:29229)
```

## Résultats mesurés (2026-11-07)
| | Run H 1 — Lisbonne | Run H 2 — Milan |
|---|---|---|
| Page de départ | maratonaclubedeportugal.com, page EDP Lisbon Half Marathon (2027) | milanomarathon.it, page `percorso` |
| Session H | `562119bf-9c35-4da8-9129-0e9cc3f7ad11` | `9ff8cf08-1449-4735-814a-ecd1ad317949` |
| Durée / étapes | 205 s / 37 | 292 s / 45 |
| Fichier | `EDP Lisbon Half Marathon 2026.kml` (19 041 o), export KML du Google My Maps intégré | GPX de 114 899 o, **source tierce** goandrace.com (le site officiel n'a qu'une image JPG) |
| Édition du tracé | **2026** (aucun tracé 2027 publié) | **2026** (selon H, la carte 2027 n'est pas encore publiée) |
| Ravitaillements | km 5, 7, 10 et 13, avec le contenu (eau, gel 226ERS, Powerade) | km 0 à 40 tous les 5 km, d'après le règlement MM27 (PDF) |
| Lecture du fichier depuis la session H | 0,64 s | 2,12 s |
| Distance mesurée | 21,21 km | 42,86 km (+1,6 % : trace Garmin) |
| D+ Mapterhorn brut / lissé / corrigé | 82 / 59 / **10 m** (pont 25 de Abril, km 0,03–3,27, corrigé) | 106 / 50 / **49 m** (tunnel km 33,9–34,1, corrigé) |
| D+ Open-Meteo (Copernicus 90 m) brut / corrigé | 487 / 13 m | non mesuré |
| Côtes > 2,5 % sur 300 m | km 5,38–5,67 (+7 m, 2,2 % en moyenne) | aucune |
| Allure de base | 4:58/km pour 1:45:00 | 5:14/km pour 3:45:00 |
| Calcul des insights | 1,7 s avec cache, dont OSRM 1,7 s | 14,4 s sans cache (14 tuiles MNT, 12,6 s) |

Rendu sur la VM de dev (rendu WebGL logiciel, sans GPU) :
| Scénario | Données | Chargement de la carte | 1er rendu complet (`idle`) | FPS du survol | Animation totale |
|---|---|---|---|---|---|
| Lisbonne, 3D | 0,45 s | 4,9 s | 18,4 s | 0,5 | 108,6 s (71 s prévues) |
| Lisbonne, `terrain=0` | 0,20 s | 2,3 s | 6,6 s | 10,5 | 71,5 s |
| Milan, `terrain=0` | 0,12 s | 2,5 s | 6,6 s | 10,6 | 71,8 s |
| Fallback, 3D | 0,52 s | 5,4 s | 17,2 s | — | — |

Captures : `data/capture_*.jpg`. Mesures brutes : `data/mesures_rendu_*.json` et `data/h_run_*.json`.

## Limites
- Le D+ dépend beaucoup du modèle numérique de terrain : 82 m bruts contre 487 m bruts pour Lisbonne. La valeur corrigée est une **estimation**, pas un chiffre officiel.
- Les deux tracés sont des éditions 2026, et celui de Milan vient d'un site tiers.
- Le lieu de retrait des dossards à Milan (Allianz MiCo) est supposé, pas vérifié.
- Les FPS en 3D sont **à mesurer sur un portable avec GPU** ; sur cette VM, le survol 3D est saccadé.
