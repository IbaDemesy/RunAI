# Voix Gladia (`runai/voice/`)

Transcription live Gladia (`solaria-1`, FR/EN/PT avec code-switching, vocabulaire personnalisé des courses et villes) et conversion des phrases en commandes typées. Les événements sont prêts à être consommés par l'app web ; ils ne pilotent pas encore les sessions H.

## Utilisation

```bash
python -m runai.voice --file audio.wav     # fichier local ou URL, envoyé au rythme réel
python -m runai.voice --mic                # micro (pip install sounddevice, non épinglé)
python -m runai.voice --keyboard           # repli clavier, sans Gladia
python -m runai.voice --file audio.wav --partials --mission-id demo   # partiels + traces/demo.jsonl
```

Une ligne JSON par événement :

- `TranscriptEvent` (`type="transcript"`) : texte partiel ou final, langue détectée, horodatage audio.
- `CommandEvent` (`type="command"`) : `command.kind` parmi `new_mission`, `pause`, `resume`, `correction`, `cancel` ; `source` = `voice` ou `keyboard` ; `early=true` pour une pause émise sur un partiel. `to_trace_event()` le convertit en `TraceEvent` du socle.

En Python : `stream_events(file_stream(...))` pour la voix, `command_from_text(texte)` pour le clavier. Les deux passent par `parse_command()` : une même phrase produit la même `VoiceCommand`.

## Règles de commandes

Parseur déterministe (regex FR/EN/PT, sans LLM). Priorité : annulation > correction > nouvelle mission > reprise > pause.

| Phrase | Commande |
| --- | --- |
| « Inscris-moi au semi de Lisbonne » | `new_mission`, Lisbonne, PT, 21,0975 km |
| « Quero correr a Meia Maratona de Lisboa » | `new_mission`, course officielle |
| « Non, attends ! » / « Stop » / « Hold on » | `pause` (dès le partiel) |
| « C'est bon, continue » | `resume` |
| « Change la date » | `correction`, cible `date` |
| « Plutôt un hôtel près du départ » | `correction`, cible `accommodation` |
| « Annule tout » / « Annule l'hôtel » | `cancel` (cible optionnelle) |

Garde-fous contre les faux positifs : la pause n'est reconnue que si le mot d'arrêt est dans les 4 premiers mots de l'énoncé (« I don't stop » en milieu de phrase est ignoré), et un énoncé de plus de 25 mots n'est jamais une commande.

## Constats en réel

- Le fichier doit être envoyé au rythme réel. Envoyé d'un coup, Gladia fusionne les énoncés (plus d'endpointing par phrase) et ferme la session avec le code 4408.
- Les partiels permettent d'émettre la pause environ 2 s avant la transcription finale de l'énoncé (1,8 s et 2,6 s mesurés).
- Les URLs `github.com/.../raw` des échantillons Gladia sont des pointeurs LFS : utiliser `media.githubusercontent.com/media/...` (le code détecte le pointeur et le signale).
