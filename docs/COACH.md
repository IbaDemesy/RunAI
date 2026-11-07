# Coach — « quel coureur es-tu ? » (`runai/coach/`)

Cinq questions à la voix → profil sportif → niveau + fourchettes de temps + verdict par distance →
3 à 5 courses ouvertes adaptées, avec une raison lisible et le statut d'inscription.
Porté depuis `spike/niveau` et `spike/trouver_courses`. Aucun appel H : les statuts non confirmés
sont marqués `a_verifier` (`needs_h_check=True`) pour un agent H **en lecture seule**, plus tard.

## API

```python
from runai.coach import QUESTIONS, extract_profile, assess, recommend_races, RacePreferences

x = extract_profile(transcript)            # ProfileExtraction
x.profile                                  # CoachProfile (≠ runai.models.RunnerProfile, identité fictive)
x.follow_up_questions                      # questions de QUESTIONS à reposer (champs invraisemblables effacés)

a = assess(x.profile)                      # Assessment
a.estimate.level, a.estimate.predictions   # debutant…expert ; TimeRange par 5k/10k/semi/marathon
a.recommended, a.not_advised, a.summary()  # distances conseillées / déconseillées ou bloquées

r = recommend_races(a, RacePreferences(origin_city="Paris", distance_km=42.195), mode="replay")
r.races[0].reason, r.races[0].status       # « 42,2 km le 04/04/2027 ; 21 semaines… », ouvert | a_verifier
r.races[0].to_race()                       # runai.models.Race pour lancer une mission
```

| Fonction | Rôle |
| --- | --- |
| `QUESTIONS` | 5 questions (fréquence/volume, sortie longue, chrono récent, ancienneté/âge, objectifs). `CUSTOM_VOCABULARY` pour Gladia. |
| `extract_profile(text, llm_json=None)` | Parseur à règles (ou JSON LLM via `llm_prompt()`), puis `plausibility_issues()` : allure, sortie > volume hebdo, chrono hors bornes → champ remis à `None` + question à reposer. Ne devine jamais (« 14 10 km » → vide). |
| `assess(profile, weeks_available=None)` | Daniels/VDOT (chrono), Cooper, sortie d'entraînement ou déclaratif ; Riegel pour la borne haute ; garde-fous (marathon < 12 sem. bloqué, débutant marathon ≥ 24 sem., < 3 sorties/sem. → marathon déconseillé, plafonds jeunes). |
| `recommend_races(assessment, preferences, mode=…)` | `replay` = cache uniquement (démo, sans réseau, `CacheMiss` sinon) ; `live` = Linkup puis écriture en cache ; `auto` = cache sinon live. Bloquant (20–60 s en live). |
| `rank_races(assessment, discovery)` | Classement déterministe sans réseau : courses citées, puis ouvertes, complétées par `a_verifier` jusqu'à 3 ; exclut complet/fermé/hors fenêtre/préparation insuffisante/doublons. |

## Mode démo (cache/fixtures)

`runai/coach/fixtures/*.json` = `DiscoveryResult` bruts (avant classement), clé = `SearchQuery.cache_key()`.
Le classement est refait à la lecture, donc un même fichier sert pour tout profil.
Préréglages dans `DEMO_PREFERENCES` : `milan` (Wizz Air Milano Marathon 04/04/2027, run Linkup réel
du 07/11/2026) et les 4 profils mesurés du spike (`debutant_10k_paris`, `semi_france`, `trail_lyon`,
`semi_etranger`). Régénérer : `recommend_races(a, DEMO_PREFERENCES["milan"], mode="live")`
(écrit dans `fixtures/`, `DiscoveryCache(dir)` pour un autre dossier).

## Mesures

Mesuré (Linkup, 07/11/2026) : 20 à 61 s par profil, 0,04 à 0,10 $ (delta de solde), 8/12 courses
« ouvertes » confirmées par H sur le spike ; run Milan : 49 s, delta de solde 0,098 $ (indicatif : clé partagée entre agents ; 0,152 $ estimés
par `FinderMetrics`), 5 courses ouvertes dont Milan. Pages Njuko (SPA) illisibles par `/fetch` →
`a_verifier` sans appel.
Estimé, à valider par un coach : bornes de confiance, semaines de préparation, plafonds d'âge,
majoration trail ; temps de trajet = vol d'oiseau (sol ×1,3 à 90 km/h, avion 750 km/h + 0,5 h).

## Intégration proposée (non implémentée)

- `GET /coach/questions` → `QUESTIONS` ; `POST /coach/profile` (transcription Gladia) → `ProfileExtraction`.
- `POST /coach/assess` → `Assessment` ; `POST /coach/races` (`RacePreferences`) → `Recommendations`
  via `anyio.to_thread.run_sync`, `mode="replay"` par défaut en démo.
- Le choix d'une course : `RaceRecommendation.to_race()` → mission existante ; `needs_h_check` →
  étape de vérification H en lecture seule avant l'inscription.
