# Spike niveau : estimer le niveau du coureur et des objectifs réalistes

Axe A de la nouvelle entrée « Quel coureur es-tu ? ». Code déterministe (pas de LLM, pas de session H) : un `RunnerProfile` Pydantic, issu des réponses vocales, donne un niveau, des fourchettes de temps (5 km, 10 km, semi, marathon), un délai de préparation et des garde-fous.

## Ce que le prototype prouve (mesuré)

- **Daniels / VDOT** : implémentation libre des équations de Daniels et Gilbert (1979) dans `runner_level.py`. Elle retrouve les tables publiées à 0,5 % près (VDOT 40, 50 et 60 sur les 4 distances, test pytest). Exemple : VDOT 50 donne 19'56, 41'20, 1h31'31 et 3h10'40 (tables : 19'57, 41'21, 1h31'35, 3h10'49).
- **4 sources de niveau**, dans cet ordre : chrono récent (Daniels + Riegel, exposant 1,06 pour la borne rapide, 1,07 à 1,12 pour la borne prudente), test de Cooper (Daniels sur 12 min et formule de Cooper, la fourchette couvre les deux), sortie récente distance + temps (allure de course supposée 3 à 15 % plus rapide), rien (fourchette selon fréquence et volume, confiance « basse »).
- **Des fourchettes, jamais une valeur unique.** La fourchette s'élargit si le chrono est ancien. Exemple : 10 km en 52' il y a 4 mois donne semi 1h53'23 à 2h01'15 et marathon 3h54'34 à 4h29'29.
- **Garde-fous** : marathon bloqué sous 12 semaines quel que soit le niveau, et sous 24 semaines pour un débutant (le test « débutant, marathon dans 6 semaines » le vérifie) ; semi bloqué pour un débutant sous 8 semaines ; marathon déconseillé sous 3 sorties par semaine ; distances maximales selon l'âge (règle FFA hors stade, **à revérifier**).
- **Tests** : `pytest spikes/niveau` donne 21 tests verts, dont les 8 profils types (débutante sans chrono, débutant marathon dans 6 semaines, intermédiaire avec un 10 km, confirmé avec un semi, sortie seule, Cooper, expert, senior avec un vieux chrono et du trail), plus un test « mineur » et des tests d'extraction vocale.
- **Gladia, mesuré le 07/11** : 2 jobs pré-enregistrés, voix de synthèse espeak-ng et profil fictif. Résultats dans `results/gladia_run_*.json` (instantanés pris avant le dernier correctif du parseur).

| Job | Audio | Temps total (upload + transcription + LLM) | transcription_time | audio_to_llm exec_time |
| --- | --- | --- | --- | --- |
| b9eaab4f-e010-4a15-a6f1-72c401d5645c | 17,4 s | 5,05 s | 2,93 s | 1,45 s |
| d2d8e205-39f9-4863-b36e-9fc8a0145779 | 22,1 s | 5,90 s | 3,33 s | 1,45 s |

  Dans les 2 jobs, « quatorze kilomètres en une heure vingt » a été transcrit « 14 10 km 1h20 ». L'`audio_to_llm` de Gladia en a tiré **100 km en 80 min**. Tous les autres champs sont justes (3 sorties, 25 km, 10 km en 3 120 s il y a 4 mois, 24 mois de pratique, 31 ans, objectifs chrono et voyage). `plausibility_issues()` détecte cette erreur (0,8 min/km, plus que le volume hebdo). Le parseur à règles laisse désormais le champ vide et le repose. Non vérifié : si l'erreur vient de la prononciation d'espeak plutôt que de Gladia avec une vraie voix.
- `gladiaio-sdk` 2.2.1 plante au décodage quand `audio_to_llm` est activé (`KeyError: 'success'`), d'où l'appel HTTP brut avec httpx dans `gladia_extract_demo.py`.

## Script vocal (5 questions, environ 1 min)

1. Combien de fois cours-tu par semaine en ce moment, et à peu près combien de kilomètres ?
2. Quelle a été ta plus longue sortie ces dernières semaines : distance, et en combien de temps ?
3. As-tu un chrono récent sur une course (5 km, 10 km, semi, marathon) ? Lequel et quand ?
4. Depuis combien de temps cours-tu, et quel âge as-tu ?
5. Qu'est-ce qui te fait envie : un premier 10 km, battre un chrono, du trail, ou courir en voyage ?

« Je ne sais pas » est une réponse valide : le champ reste à `null` et RunAI estime le niveau à partir du reste.

## Extraction voix → JSON

Gladia live (`language_config.languages=["fr"]`, vocabulaire personnalisé `CUSTOM_VOCABULARY`), puis la transcription finale passe dans un LLM avec `llm_prompt()`. Le prompt inclut le schéma JSON de `RunnerProfile` et la règle « null si non dit ». Ensuite `parse_llm_json()` valide le résultat avec Pydantic, puis `plausibility_issues()` vérifie les allures et les volumes. Un champ incohérent est remis à `null` et reposé à la voix. Ce qui a été mesuré : en pré-enregistré, `audio_to_llm` de Gladia sert de LLM sans autre clé. En live, la doc consultée ne montre pas d'audio_to_llm, donc il faut un LLM de l'orchestrateur. `extract_rule_based()` sert de secours sans LLM.

## Strava : API officielle (lecture de la doc le 07/11, rien n'a été appelé)

- OAuth 2 : `https://www.strava.com/oauth/authorize`, puis `POST /oauth/token`. L'access token expire après 6 h et se renouvelle avec un refresh token. `localhost` est accepté comme redirect.
- Scopes utiles : `activity:read` (activités visibles par tous ou par les abonnés), `activity:read_all` (y compris « Only You »), `profile:read_all`. L'utilisateur peut décocher des scopes.
- Données lues : `GET /athlete/activities` (liste, filtres `before`/`after`), `GET /activities/{id}` (`DetailedActivity` avec `best_efforts`), `GET /athletes/{id}/stats` (seulement les activités publiques).
- Limites : 200 requêtes par 15 min et 2 000 par jour au total ; 100 par 15 min et 1 000 par jour en lecture. Une nouvelle app est en « Single Player Mode » (1 athlète). Passer à 10 athlètes se fait depuis le tableau de bord ; au-delà, il faut une revue Strava.
- Contraintes : d'après la page Getting started, un abonnement Strava est requis pour créer une app. L'API Agreement (1er juin 2026) dit que les données d'un utilisateur ne sont montrées qu'à lui. Pas de scraping (CGU).
- **Coût estimé : 4 à 6 h** (OAuth + refresh, lecture de 8 semaines d'activités, best efforts vers `RecentRace`/`RecentRun`, volume hebdo). Démo limitée au compte d'un membre de l'équipe. À traiter en option P2 : la voix suffit pour la démo.

## Relancer

```bash
.venv/bin/pytest -q spikes/niveau
.venv/bin/ruff check spikes/niveau
cd spikes/niveau && GLADIA_API_KEY=... ../../.venv/bin/python gladia_extract_demo.py   # requiert espeak-ng ; 1 job Gladia
```

Estimé, non mesuré : les bornes du mode déclaratif (table volume → VDOT), le facteur « sortie → course » (3 à 15 %), les semaines minimales par niveau et la règle trail (km + D+/100, puis +10 à +25 %). Ce sont des règles de bon sens à faire valider par un coach.
