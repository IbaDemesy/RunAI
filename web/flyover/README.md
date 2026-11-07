# Survol 3D du parcours (`web/flyover/`)

Page web statique, sans build ni clé API : elle charge un tracé GPX (ou KML), l'affiche en 3D avec [MapLibre GL JS](https://maplibre.org/) 5.24.0 et fait suivre le tracé par la caméra en accéléré. Contexte : section 4.3 de [EXPLORATION.md](../../docs/EXPLORATION.md) (F12, bonus visuel).

## Ouvrir en local

Depuis la racine du dépôt :

```bash
python3 -m http.server 8000 --directory web/flyover
```

Puis ouvrir <http://localhost:8000/>. La page charge le GPX d'exemple et montre la vue d'ensemble ; « Lecture » lance le survol.

Un serveur local est nécessaire pour charger un GPX par URL. En ouvrant directement `index.html` (`file://`), le navigateur bloque ce chargement : la page l'indique, et le bouton « Ouvrir un GPX ou KML… » ou le glisser-déposer fonctionnent quand même. Une connexion Internet est requise (MapLibre depuis unpkg, tuiles).

Paramètres d'URL, combinables :

| Paramètre | Effet | Exemple |
| --- | --- | --- |
| `gpx` | Tracé à charger (même origine, ou URL avec CORS) | `?gpx=samples/lisbonne-collines-exemple.gpx` |
| `duration` | Durée du survol complet, en secondes (défaut 60) | `?duration=120` |
| `autoplay=1` | Lance le survol au chargement | `?autoplay=1` |
| `km` | Place la caméra au km donné | `?km=7` |
| `basemap=satellite` | Fond Sentinel-2 au lieu du plan OSM | `?basemap=satellite` |
| `exaggeration` | Exagération du relief (défaut 1,5) | `?exaggeration=2` |
| `capture` | Garde le buffer WebGL pour les captures d'écran | `?capture=1` |

Raccourcis : Espace pour lecture/pause, flèches gauche/droite pour ±500 m. Cliquer ou glisser sur le profil d'altitude déplace la caméra.

## Ce que fait la page

- Relief 3D et ombrage à partir des tuiles [Mapterhorn](https://tiles.mapterhorn.com/tilejson.json) (terrarium, sans clé).
- Tracé coloré selon la progression, marqueurs départ, arrivée (fusionnés si boucle) et un marqueur par kilomètre.
- Caméra qui suit le tracé à vitesse constante, cap lissé vers un point 250 m plus loin. On peut zoomer pendant le survol.
- Profil d'altitude synchronisé avec la caméra, D+/D− estimés après lissage sur 100 m.
- Altitudes : celles du fichier (`<ele>`) si tous les points en ont, sinon lues dans les tuiles Mapterhorn au zoom 12 (environ 20 m par pixel à Lisbonne).
- API JavaScript pour l'app ou les commandes vocales : `RunAIFlyover.seekKm(7)`, `play()`, `pause()`, `overview()`, `loadText(gpx)`, `loadUrl(url)`, `setDuration(s)`, `state`.

## Fonds de carte et attributions

Les attributions sont affichées en bas à droite, sans repli, pour chaque source visible.

| Source | Usage | Licence / conditions |
| --- | --- | --- |
| [Mapterhorn](https://mapterhorn.com/attribution) | Relief et ombrage | Attribution « © Mapterhorn » ; détail des MNT sur la page d'attribution |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Plan par défaut, `tile.openstreetmap.org` | ODbL ; [politique d'usage des tuiles](https://operations.osmfoundation.org/policies/tiles/) : usage léger, pas de préchargement massif |
| [Sentinel-2 cloudless 2020, EOX](https://s2maps.eu) | Fond satellite optionnel | CC BY-NC-SA 4.0 : usage non commercial ; à remplacer pour un produit commercial |

## GPX d'exemple

[`samples/lisbonne-collines-exemple.gpx`](samples/lisbonne-collines-exemple.gpx) : boucle de 9,97 km dans les collines de Lisbonne (Praça do Comércio, Sé, Graça, Senhora do Monte, Avenida da Liberdade, Parque Eduardo VII, Príncipe Real, Chiado, Cais do Sodré), 331 points, altitudes de 3 à 110 m.

**Ce n'est pas le tracé d'une course officielle.** Les 15 points de passage ont été placés à la main, l'itinéraire piéton calculé par le routeur OSRM de [routing.openstreetmap.de](https://routing.openstreetmap.de/) sur les données OpenStreetMap (© contributeurs OSM, ODbL), les altitudes viennent d'[Open-Meteo](https://open-meteo.com/en/docs/elevation-api) (Copernicus DEM GLO-90). Pour le régénérer :

```bash
.venv/bin/python web/flyover/tools/build_sample_gpx.py
```

Pour un vrai parcours (semi de Lisbonne, marathon de Milan), utiliser le GPX/KML publié par l'organisateur pour l'édition visée, en citant la source ; ne pas le versionner sans vérifier sa licence.

## Limites connues

- Ponts et tunnels : le tracé est plaqué sur le MNT, donc il « descend » au niveau de l'eau sur un pont (le 25 de Abril au départ du semi de Lisbonne, par exemple), et le profil suit le sol, pas le tablier. Pas de correction automatique.
- D+ indicatif : il dépend du MNT et du lissage (293 m sur l'exemple avec lissage à 100 m, 451 m sans lissage). Afficher une fourchette, pas un D+ officiel.
- Parseurs GPX/KML volontairement simples (expressions régulières) : `trkpt`, sinon `rtept`, et `LineString`/`gx:coord` en KML. Un seul tracé fusionné si le fichier contient plusieurs segments.
- Vitesse de la caméra constante sur la distance ; pas d'export vidéo (F33).

## Tests

```bash
node --test web/flyover/tests/   # fonctions pures de route.js
pytest -q tests/test_flyover.py  # GPX d'exemple, versions épinglées, attributions, et lance les tests Node si node est présent
```
