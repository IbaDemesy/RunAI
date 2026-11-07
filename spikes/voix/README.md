# Spike voix — la voix comme télécommande des agents H

Page web (micro navigateur ou injection d'un WAV) → FastAPI → **Gladia live** (fr, partiels + finaux)
→ détection d'intention → pilotage d'une **session H** (`pause` / `resume` / `send_message`).
« je valide » = validation humaine enregistrée, **aucune soumission ni paiement**.

## Ce qui est prouvé (MESURÉ)

- Gladia live fr renvoie des partiels exploitables : « stop » détecté **avant la fin de la phrase**.
- Pause, reprise et correction vocale pilotent une vraie session H (lecture seule, Wikipédia),
  et l'agent **comprend la correction** : événement H observé
  « The user corrected the request: they actually want the Paris Half Marathon (Semi-marathon de Paris) ».
- La page web fonctionne avec un micro (testé avec le faux micro de Chrome alimenté par le WAV de test).

## Résultats mesurés (audio gTTS injecté en temps réel, 4 phrases)

| Mesure | Run H 2 (`d8018b1e-3956-4cc4-841b-c66ebe564fa4`) | Run H 1 (`25165c8c-1caa-4a07-8ed2-db1416c165c1`) |
|---|---|---|
| Session Gladia | `6d0c3918-…` | `66697d1a-…` |
| Init Gladia (POST + WS) | 1,41 s | 1,55 s |
| Début de parole → `speech_start` | 343–428 ms | 368–402 ms |
| Fin de mot → partiel (n=16) | médiane 438 ms, p90 1,03 s, max 1,08 s | médiane 406 ms, p90 1,03 s |
| Fin d'énoncé → final | 0,86–1,08 s | — |
| Partiel → intention (regex) | < 0,2 ms | < 0,3 ms |
| Fin du mot « stop » → intention pause | 390 ms | — |
| Appel `pause` → statut `paused` | 0,44 s (1er), 2,04 s (2e) | 2,59 s ; 2e pause jamais vue (session `completed`) |
| Appel `resume` → `running` | 0,73 s | 0,77 s |
| `send_message` : appel / retour `running` | 235 ms / 447 ms | échec 422 (bug corrigé depuis) |
| `send_message` → événement user visible | 0,59 s | — |
| `send_message` → raisonnement de l'agent sur la correction | **2,85 s** | — |
| Création H → `running` | 5,8 s | 7,0 s |

Quota H vérifié avant chaque création (`limit=3 active=1 available=2`). 2 runs H au total, tous deux annulés
(statut final : run 1 `completed` avant la fin du scénario, run 2 `interrupted` après annulation). Détails : `results/run_h_*.json` et `.log`.

Test navigateur (faux micro, session Gladia `fb8b5a43-d838-4a0b-8acb-5b715361a4ce`, dry-run H) : 5 intentions
détectées (pause, resume, pause « Non », correction, validate), `speech_start` à 0,03 s d'audio (le buffer
pendant l'ouverture Gladia ne perd rien).

## ESTIMÉ / non mesuré

- Latence avec une vraie voix humaine et un vrai micro dans le bruit d'une salle de hackathon : non mesurée
  (attendu du même ordre, ~0,4–1 s, mais les partiels seront moins propres).
- Pilotage de 3 sessions H en parallèle par la voix : non testé (1 seule session côté spike).

## Limites connues

- **Gladia gratuit : 1 session live à la fois** → verrou global côté serveur ; HTTP 429 traité comme « déjà ouverte ».
  Un seul micro pour toute la démo.
- Intentions par regex : « Non » en début de phrase = pause (puis correction sur le final) ; espeak-ng est mal
  transcrit, utiliser gTTS ou une vraie voix.
- `pause` H est asynchrone : 0,4 à 2,6 s avant `paused` effectif (l'agent finit son action en cours).
- `send_message` sur une session terminée la relance (et reprend un slot) → le code refuse la correction si la
  session est `completed/failed/timed_out/interrupted/idle`.

## Relancer

```bash
pip install fastapi uvicorn websockets   # + hai-agents (requirements.txt)
# variables : GLADIA_API_KEY, HAI_API_KEY (jamais loggées)
python spikes/voix/make_audio.py gtts          # (pip install gTTS) ou: espeak
python spikes/voix/bench.py --audio spikes/voix/audio/scenario_gtts.wav            # Gladia seul (dry-run H)
python spikes/voix/bench.py --h --audio spikes/voix/audio/scenario_gtts.wav --out spikes/voix/results/run.json
uvicorn server:app --app-dir spikes/voix --port 8765   # puis http://127.0.0.1:8765
```

Dans la page : « Démarrer H » (session lecture seule, quota vérifié), « Micro » ou « Injecter audio »,
« Annuler H » à la fin (toujours : une session en pause garde son slot).
