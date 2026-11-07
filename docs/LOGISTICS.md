# Logistique du week-end et « feu vert règlement » (`runai/logistics/`)

Avant de proposer une course, RunAI lit le règlement (sourcé champ par champ), dit si le coureur peut s'inscrire et si son objectif est réaliste, puis assemble la timeline du week-end (transport, retrait du dossard, hôtel, sas, départ, barrières, retour) avec des alertes. Aucun appel H. Linkup n'est appelé que si ni la fixture ni le cache ne couvrent la course.

## API

```python
from runai.logistics import (
    extract_rules, eligibility, build_timeline, to_ics,
    RunnerSituation, RunnerGoal, TransportLeg, HotelStay,
)

rules = extract_rules(race)                       # Race (runai.models) ou nom de course
verdict = eligibility(rules, profile, RunnerSituation(residence_country="FR"),
                      RunnerGoal.parse("3h45-3h55", rules.distance_km))
timeline = build_timeline(race, rules, arrival=train_aller, hotel=hotel,
                          departure=train_retour, goal=goal)
open("week-end.ics", "w").write(to_ics(timeline))
```

| Fonction | Rôle |
| --- | --- |
| `extract_rules(race, *, client=None, cache_dir=None, use_fixtures=True, refresh=False, depth="standard") -> RaceRules` | Ordre : fixture vérifiée (`fixtures/*.json`, nom + alias + année), cache disque (`RUNAI_LOGISTICS_CACHE`, défaut `traces/logistics-cache/`), puis Linkup `search` structuré (`finishers.com` exclu). `rules.source_url("time_limit")` donne l'URL de chaque champ ; `rules.missing_fields` liste les champs critiques non trouvés (jamais devinés). |
| `eligibility(rules, profile=None, situation=None, goal=None, *, today=None) -> Eligibility` | `light` vert / orange / rouge, `reasons` (chacune avec `source_url`), `human_todo` (documents et actions que l'humain fournit lui-même : pas de champ « fait », l'agent ne coche rien), `entry_path_id` + `alternative_path_id`. |
| `build_timeline(race, rules, arrival=None, hotel=None, departure=None, goal=None) -> Timeline` | `events` datés avec le fuseau de la course (`event.in_timezone("Europe/Paris")` pour convertir), `assumption=True` pour ce qui est estimé ; `alerts` (`bloquant` / `attention` / `info`) ; `timeline.ok` faux si une alerte bloque. |
| `to_ics(timeline) -> str` | Calendrier RFC 5545 (UTC), événements estimés suffixés « (estimé) ». |

Les heures des `TransportLeg` / `HotelStay` sans fuseau sont lues dans le fuseau de la course.

## Feu vert règlement

- **Inscription** : la voie d'inscription est choisie selon licence (FIDAL, fédération étrangère World Athletics), résidence, Runcard, certificat et envie de compétition. Âge minimum et date de clôture sont contrôlés. Une pièce manquante donne orange + un `HumanTodo`. Une voie impossible (âge, clôture passée) donne rouge.
- **Objectif** : comparé au temps limite et à chaque barrière (allure constante). Rouge si dépassé, orange si la marge est < 10 %, vert sinon. Avec un résultat récent, une prédiction Riegel (exposant 1,06) signale un objectif trop ambitieux.
- **Règlement inconnu** : un champ critique manquant ne donne jamais vert.

Exemple Milan 2027 (fixture) : un Français sans licence qui vise 3h45-3h55 est **orange**. L'objectif est vert face au temps limite (6h30) et aux barrières (km 21,1 à 3h15, km 27,8 à 4h20), mais il doit fournir lui-même une Runcard FIDAL et un certificat d'aptitude à la compétition aux normes italiennes (visite, analyse d'urine, ECG au repos et à l'effort, spirographie). Alternative : « sport tourism », non compétitive. Un objectif à 6h45 est **rouge**.

## Timeline et alertes

Codes d'alerte : `bib_pickup_missed` (transport arrivant après la dernière fermeture du retrait, avec rappel « pas de retrait le jour J » et délégation possible), `bib_pickup_unknown`, `start_time_unknown`, `arrival_after_start`, `hotel_nights` (nuit avant la course non couverte), `late_checkout` (check-out avant l'arrivée estimée), `return_too_early` (retour avant arrivée + douche + trajet), `finish_after_limit`, `pace_assumed`. Le réalisme face aux barrières est jugé par `eligibility`. Les durées estimées (réveil 2h30 avant, trajet hôtel → départ, marge après l'arrivée) sont marquées `assumption`.

## Fixture Milan

`fixtures/wizz-air-milano-marathon-2027.json`, vérifiée le 7/11/2026 sur le règlement officiel 2027 ([règlement](https://indd.adobe.com/view/b16c5256-1bb0-4ca9-97a3-82c6730745ba), [infos pratiques](https://www.milanomarathon.it/fr/informations-pratiques/), [schéma d'inscription](https://www.milanomarathon.it/wp-content/uploads/2026/07/entry_flowchart_MM27_ENG_V02.pdf)). Le lieu précis du départ 2027 n'est pas publié : il reste dans `missing_fields`.

## Limites

- Linkup `standard` (~6 s) ne ramène pas les champs détaillés sur Milan ; `deep` (~2 min) en ramène plus mais s'est trompé sur la délégation du retrait. Pour une course de démo, préférer une fixture vérifiée.
- Le réalisme se base sur une allure constante, sans dénivelé ni chaleur.
