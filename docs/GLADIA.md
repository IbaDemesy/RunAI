# Stratégie pour le prix « Best Use of Gladia » (1 000 €)

## Principe

Aujourd'hui, Gladia ne fait que le STT : n'importe quel concurrent pourrait le remplacer. Pour se distinguer, **Gladia doit être indispensable à chaque étape de la démo** : dicter, comprendre, corriger, arrêter, récapituler.

## Ce que la documentation confirme

Vérification documentaire pour le **live WebSocket, `model="solaria-1"`** ; pas encore un test des fonctions sur nos voix. Initialisation via [POST /v2/live](https://docs.gladia.io/api-reference/v2/live/init).

| Fonction | Live | Pré-enregistré | Paramètres et source |
| --- | --- | --- | --- |
| Traduction | Oui, en temps réel | Oui | `realtime_processing.translation=true`, `realtime_processing.translation_config.target_languages=["fr"]`, `.model="base"` ou `"enhanced"` ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/translation) |
| Diarisation des locuteurs | Non trouvée dans le schéma live ; guide limité au pré-enregistré | Oui | `diarization=true`, `diarization_config.number_of_speakers`, `.min_speakers`, `.max_speakers` ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/speaker-diarization) |
| Entités nommées (NER) | Oui, **Alpha** | Oui | `realtime_processing.named_entity_recognition=true` ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/named-entity-recognition) |
| Vocabulaire personnalisé | Oui | Oui | `realtime_processing.custom_vocabulary=true`, `realtime_processing.custom_vocabulary_config.vocabulary`, `.default_intensity` ; entrées `value`, `pronunciations`, `intensity`, `language` ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/custom-vocabulary) |
| Code-switching | Oui | Oui, avec Solaria-1 | `language_config.languages=["fr","en","pt"]`, `language_config.code_switching=true` ; [documentation](https://docs.gladia.io/chapters/language/code-switching) |
| Résumé | Oui, **en post-traitement de la session**, pas en continu | Oui | `post_processing.summarization=true`, `post_processing.summarization_config.type="general"`, `"concise"` ou `"bullet_points"` ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/summarization) |
| Audio-to-LLM | Non trouvé dans le schéma live ; documenté pour le pré-enregistré seulement | Oui | `audio_to_llm=true`, `audio_to_llm_config.prompts=[...]`, `.model` facultatif ; [documentation](https://docs.gladia.io/chapters/audio-intelligence/audio-to-llm) |

En WebSocket, activer `messages_config.receive_realtime_processing_events=true` pour recevoir les événements NER/traduction, et `messages_config.receive_post_processing_events=true` pour le résumé. En pré-enregistré, les options `translation`, `translation_config`, `named_entity_recognition`, `custom_vocabulary`, `custom_vocabulary_config`, `summarization` et `summarization_config` sont à la racine de la requête, sans les conteneurs live.

## Idée 1 — Stop instantané sur transcription partielle

**Live confirmé** : `messages_config.receive_partial_transcripts=true`. Dès qu'un partiel (`data.is_final=false`) contient « stop », « attends » ou « non », RunAI demande `pause()` sur l'agent H concerné, **avant la fin de la phrase**. C'est notre moment latence + **supervision**.

**Moment démo** : « Non, attends… » ; l'agent se met en pause pendant que le coureur finit sa correction.

« Instantané » est l'objectif UX, pas une garantie : délais réseau/H à mesurer. Dédupliquer les appels par énoncé (`data.id`), gérer les faux positifs et n'autoriser la reprise qu'après confirmation. Les partiels sont révisables et moins précis avec plusieurs langues.

Docs : [transcriptions partielles](https://docs.gladia.io/chapters/live-stt/features/partial-transcripts), [pause et pilotage H](https://hub.hcompany.ai/agents-api/observe-and-steer).

## Idée 2 — Profil coureur dicté en une fois

**NER et vocabulaire personnalisé confirmés en live** : en 30 s, le coureur dicte son profil. Vocabulaire : **PPS, FFA, semi, Njuko, Klikego**. RunAI convertit les entités et le texte en champs, les fait confirmer, puis réutilise le profil dans tous les formulaires.

**Moment démo** : une seule dictée remplit la fiche coureur, puis alimente les trois agents H.

La NER est en Alpha : vérifier la qualité en français ; aucune entité « numéro PPS » spécialisée n'est documentée. Le vocabulaire aide à transcrire, il ne construit pas le profil à lui seul. Extraction métier et validation restent dans RunAI ; le PPS est fourni par le coureur, jamais obtenu à sa place.

## Idée 3 — Courses à l'étranger

**Code-switching et traduction confirmés en live** : FR/EN/PT pour les échanges et noms de courses, puis traduction du transcript vers le français si utile. Limiter les langues à celles attendues : la détection se fait par énoncé et ne garantit pas chaque nom propre isolé.

**Moment démo** : « Je veux courir la Meia Maratona de Lisboa » ; le nom est conservé, la demande comprise et le récap affiché en français.

## Idée 4 — Mode club par diarisation

**Pré-enregistré seulement dans la documentation vérifiée** : réunion enregistrée → diarisation → une fiche et une inscription par coureur, en parallèle sur H.

**Moment démo** : trois personnes parlent, puis trois profils confirmés déclenchent trois inscriptions.

Spectaculaire mais risqué : les labels `speaker` distinguent les voix, ils n'identifient pas les personnes. Faire confirmer l'association voix/profil et les données avant toute action. **Bonus seulement si le reste tient dimanche matin.**

## Idée 5 — Débrief vocal de fin de mission

**Résumé live en post-traitement confirmé ; Audio-to-LLM pré-enregistré seulement** : à la fin de la conversation, fermer le flux audio pour obtenir le résumé, ou envoyer l'enregistrement au pré-enregistré avec un prompt listant demandes et corrections. Afficher le récap avant validation, sans présenter cela comme un LLM live.

**Moment démo** : « Tu as demandé un hôtel proche du départ, puis corrigé les dates : voici ce qui est prêt. » Le coureur confirme à la voix ; aucun paiement ni réservation finale n'est soumis.

Le résumé porte sur la conversation, pas sur une preuve de réservation : le croiser avec le récap H. **Pas de TTS Gladia trouvé** dans la documentation consultée : synthèse du navigateur ou texte à l'écran.

## Recommandation / coût

- **1 + 2 + 3 en P1 : environ 2 à 3 h estimées**, surtout réglages et logique applicative, puis essais en français et avec bruit.
- **4 en bonus** seulement ; 5 si le temps de post-traitement tient dans la démo.
- Clé Gladia côté backend, faux profils pour la démo, consentement avant enregistrement. Tarifs d'API et suppléments à vérifier séparément du temps de développement.
- Périmètre et articulation avec les autres partenaires : [BRAINSTORM.md](BRAINSTORM.md).
