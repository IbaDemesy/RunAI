# Spike axe E — canal téléphone + Telegram

Canaux en plus de la PWA, branchés sur le même contrat d'orchestrateur (`orchestrator.py`, mock : aucune session H créée).
Tout est en données fictives (Camille Martin, camille.martin@example.com, née le 12/05/1994). Aucun paiement, aucune soumission.

## Ce qui est prouvé (mesuré, sans compte Twilio ni token Telegram)

| Brique | Preuve | Résultat mesuré |
|---|---|---|
| Gladia Live accepte l'audio téléphone brut | `bench_gladia_mulaw.py` : Piper FR → μ-law 8 kHz, trames 20 ms en temps réel, `encoding=wav/ulaw, sample_rate=8000, bit_depth=8` (pas d'en-tête WAV, payload Twilio passé tel quel) | 15 sessions OK. Final après fin de parole (endpointing 0.1) : médiane **641 ms**, max 885 ms ; endpointing 0.3 : médiane 807 ms. Init session (POST /v2/live + WS) ≈ 1,0–1,5 s |
| 8 kHz vs 16 kHz | même bench `--pcm16k` | PCM 16 kHz : médiane 764 ms, WER moyen 0,191 vs 0,245 en μ-law (écart dû surtout à la phrase e-mail) |
| Custom vocabulary | `--no-vocab` | sans vocab : « semi » → « semis » (WER 0,11) ; avec vocab : « semi » correct mais e-mail → « Mon adresse est semi-marathon » (sur-correction) |
| Appel complet simulé | `fake_twilio_call.py` : faux client Twilio Media Streams (connected/start/media/mark) contre `phone_server.py`, Gladia Live réel, TTS Piper, mock orchestrateur | Run OK (session Gladia `8e47e660-0a8f-4d7f-8661-9080461e38b2`) : fin de parole appelant → 1er audio RunAI **763 ms** (tour 1) et **1 077 ms** (tour 2) ; transcript final → 1er audio envoyé 191 / 91 ms ; mission `m0001` lancée, notifier appelé, raccroché par le serveur |
| TTS local | `bench_tts.py` (3 essais/phrase, CPU de la VM) | Piper `fr_FR-siwis-medium` : chargement 1 202 ms, 23–145 ms par phrase (RTF ≈ 0,025) ; espeak-ng : 13–44 ms (RTF ≈ 0,01–0,02), voix robotique |
| Note vocale Telegram → Gladia pré-enregistré | `bench_telegram_voice.py` : Piper → OGG/Opus 48 kHz (format note vocale) → upload + job + poll | 4 jobs, WER 0 ; total **2,1–4,2 s** (upload 0,8–1,7 s) |
| Bot Telegram | `tests/test_telegram_bot.py` avec un faux transport Bot API (`BaseRequest`) : vrai `Application` PTB 22.8, vrais handlers | note vocale → getFile/download → transcription → message de suivi édité en place (7 `editMessageText` sur le même `message_id`) → 3 `sendPhoto` avec boutons Je valide / Refuser / Voir → décisions → PDF + .ics + GPX ; `/start` avec bouton position + Mini App ; position ; `web_app_data` ; validation HMAC `initData` |
| Téléphone | `tests/test_phone_server.py` (faux STT/TTS, TestClient) | TwiML `<Say>` + `<Connect><Stream wss://…>`, signature `X-Twilio-Signature` (vecteur de la doc Twilio recoupé avec `twilio` 9.13.0), barge-in → `clear`, piste outbound ignorée, raccrochage après marks |

**Échecs observés (non masqués)** : sur 3 appels simulés, 1 run a raté (session `ab91465b-…`) : Gladia a transcrit « semi » en « chemise » → le dialogue redemande la distance, pas de lancement. Hallucinations de fin d'énoncé : « Oui, vas-y **Greg** », « 10 km. **Maître** ». L'audio est synthétique (Piper), pas une vraie voix au téléphone : les chiffres réels seront moins bons.

## Estimé (non mesuré)

- Réseau téléphonique + Twilio ajoutent ≈ 100–300 ms par sens : latence perçue attendue ≈ 1,0–1,5 s par tour.
- ElevenLabs Flash v2.5 (~100 ms serveur annoncés par la doc, sortie native `ulaw_8000`) et OpenAI `gpt-4o-mini-tts` (PCM 24 kHz) : **non mesurés**, `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` absentes. Code prêt dans `tts.py` (`RUNAI_TTS=elevenlabs|openai`).

## Relancer

```bash
python -m venv ~/venv_tt && ~/venv_tt/bin/pip install -r spikes/telephone_telegram/requirements.txt
mkdir -p ~/piper_voices && cd ~/piper_voices && for e in onnx onnx.json; do curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.$e; done
cd spikes/telephone_telegram
~/venv_tt/bin/pytest -q                      # 18 tests, sans aucune clé
~/venv_tt/bin/python bench_tts.py            # TTS locaux (+ ElevenLabs/OpenAI si clés)
GLADIA_API_KEY=... ~/venv_tt/bin/python bench_gladia_mulaw.py [--pcm16k] [--no-vocab]
GLADIA_API_KEY=... ~/venv_tt/bin/python fake_twilio_call.py
GLADIA_API_KEY=... ~/venv_tt/bin/python bench_telegram_voice.py
```
Résultats JSON dans `results/`. Plan gratuit Gladia : 1 session Live simultanée (ne pas lancer deux benchs Live en parallèle).

Vrai appel : `PUBLIC_HOST=<sous-domaine>.ngrok-free.app TWILIO_AUTH_TOKEN=... uvicorn phone_server:app --port 8080`, puis dans la console Twilio, numéro → *A call comes in* → Webhook `POST https://<hôte>/twilio/voice`.
Vrai bot : `TELEGRAM_BOT_TOKEN=... RUNAI_PWA_URL=https://... python telegram_bot.py` (polling, aucune URL publique nécessaire) ; webhook optionnel via `TELEGRAM_WEBHOOK_URL=https://<hôte>/telegram`.

## Comptes / clés nécessaires

- **Telegram** : token `@BotFather` (`/newbot`) → `TELEGRAM_BOT_TOKEN`. Mini App : URL **HTTPS** publique de la PWA (`RUNAI_PWA_URL`) ; optionnel `/setmenubutton` ou `/newapp` chez BotFather. Webhook seulement si on ne fait pas de polling (HTTPS, ports 443/80/88/8443).
- **Téléphone** : compte Twilio (Account SID + Auth Token), un numéro, une URL publique HTTPS/WSS (ngrok, Cloudflare Tunnel ou déploiement) ; `GLADIA_API_KEY` (présente) ; optionnel `ELEVENLABS_API_KEY` ou `OPENAI_API_KEY`.
- **Lien appel → Telegram** (« je t'envoie tout ») : table numéro appelant → `chat_id` (l'utilisateur fait `/start` une fois et partage son contact), sinon SMS Twilio. Actuellement `LogNotifier` (mock).

## Twilio : limites d'essai et alternatives (documenté, non testé : à confirmer dans la console)

- Essai (doc Twilio) : 30 jours, crédit offert, jusqu'à 5 numéros vérifiés, appels uniquement depuis/vers **numéros vérifiés**, message d'essai lu au début de chaque appel (« sent from a Twilio trial account… », à passer par une touche), numéro d'essai **US** en général. Numéro **FR** : exige un *Regulatory Bundle* (justificatif d'adresse/identité), délai de validation → irréaliste d'ici dimanche ; un numéro US appelé depuis la France coûte l'international à l'appelant.
- Prix relevés (page Twilio FR) : entrant numéro local 0,0100 $/min, numéro local 1,35 $/mois, Media Streams 0,0044 $/min.
- Alternatives : **Telnyx** (Media Streaming WebSocket compatible, numéros FR possibles avec justificatifs), **Vonage** (WebSocket audio L16 16 kHz), **Plivo** (Audio Streams, μ-law 8 kHz). Aucun gain décisif pour un hackathon : Twilio a la meilleure doc et l'intégration Pipecat.
- **Pipecat** : `GladiaSTTService` + `TwilioFrameSerializer` + ElevenLabs/OpenAI/Piper natifs → réduit le code (VAD, barge-in, pipeline) mais ajoute une dépendance lourde ; **LiveKit Agents** : plugin Gladia natif, mais téléphonie via SIP LiveKit (compte + trunk SIP en plus). Le spike garde FastAPI direct (~250 lignes) qui se greffe sur le backend RunAI.

## Verdict par brique

| Brique | Verdict | Effort restant | Valeur démo | Valeur prix Gladia | Risques | Plan B |
|---|---|---|---|---|---|---|
| Twilio ↔ Gladia Live μ-law | faisable, prouvé en simulé | 1–2 h (compte + ngrok + test réel) | forte (« j'appelle RunAI ») | forte : STT temps réel téléphonique, partials, endpointing, vocab | message d'essai, numéro US, réseau | appel joué en vidéo / navigateur (même pipeline via WebSocket) |
| Dialogue + « je m'en occupe, je t'envoie tout » | faisable, prouvé | 1 h (brancher le vrai orchestrateur) | forte | moyenne | erreurs STT sur la distance/ville | confirmation systématique + reformulation (déjà fait) |
| TTS | Piper local faisable, prouvé | 0,5 h pour ElevenLabs si clé | moyenne (Piper correct, pas premium) | nulle (pas Gladia) | qualité voix | `<Say>` Twilio (voix Google FR) |
| Telegram vocal + suivi + validation + docs | faisable, prouvé en tests | 1 h (token réel + brancher le backend) | forte (validation « Je valide » sur téléphone) | moyenne (pré-enregistré, 2–4 s) | rate-limit edit (~1 édition/s par chat), photo 1×1 du mock à remplacer par la vraie capture H | PWA seule |
| Mini App | faisable (bouton prouvé, HMAC initData prouvé) | dépend de l'URL HTTPS de la PWA | moyenne | nulle | `sendData` ne marche que depuis un bouton clavier | lien URL classique |
