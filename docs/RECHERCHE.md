# Recherche de course (`runai/search/`)

À partir d'une demande libre (« semi de Lisbonne 2027 », « marathon de Milan »), `search_race()` renvoie une fiche `RaceSheet` sourcée, vérifiée en code. `RaceSheet.to_race()` la convertit en `Race` du socle.

```bash
python -m runai.search "semi de Lisbonne 2027"            # appel réel Linkup + géocodage
python -m runai.search "marathon de Milan 2027" --no-geo  # sans géocodage
```

## Déroulé

1. **Recherche structurée** Linkup `/search` (`depth="deep"`, `output_type="structured"`, schéma `RACE_SCHEMA`) : nom, ville, pays, date, heure, distance, site officiel, lien d'inscription, départ, retrait du dossard (lieu, adresse, jours, horaires) et l'URL lue pour chaque information clé.
2. **Seconde passe** si des champs manquent : nouvelle recherche limitée aux domaines du site officiel et de la plateforme d'inscription (`include_domains`), qui ne remplit que les champs vides.
3. **Lien d'inscription** : accepté s'il est sur le domaine officiel ou une plateforme connue (`KNOWN_REGISTRATION_PLATFORMS` : Njuko, Klikego, Time To, ENDU…). Sinon, la page officielle est lue avec `/fetch` : le lien doit y figurer, ou il est remplacé par le lien d'inscription qu'elle contient (avec un avertissement). Un agrégateur (Ahotu, World's Marathons…) est une erreur.
4. **Contrôles** (`check_sheet`) : date dans le futur et de l'édition demandée, distance cohérente avec la demande (semi ≈ 21,1 km, marathon ≈ 42,2 km), heure au format `HH:MM`, retrait du dossard dans les 10 jours avant la course, au moins une source.

Les champs introuvables restent vides et sont listés dans `missing_fields` ; les problèmes sont dans `issues` (`error` ou `warning`). `is_reliable` est faux dès qu'il y a une erreur.

## Coordonnées

`locate_race(sheet)` géocode le départ et le retrait du dossard avec Nominatim (OpenStreetMap, sans clé, 1 requête par seconde). Linkup fournit un nom de lieu en langue locale (`*_geocode_query`) ; on essaie ensuite l'adresse puis le nom. Un résultat à plus de 30 km de la ville est rejeté. Si rien ne correspond, la coordonnée vaut `None` : jamais de centre-ville par défaut.

## Pour les agents H

`search_race_tool(request)` renvoie la fiche en JSON, avec une docstring prête pour `tools=[...]` du SDK H.

## Coût

Environ 0,055 $ par recherche `deep`, une seconde recherche si des champs manquent, et 0,005 $ par `/fetch` quand le lien d'inscription doit être vérifié.
