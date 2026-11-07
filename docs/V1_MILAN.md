# V1 réelle — Marathon de Milan

## Modes

`RUNAI_DEMO=1` force les services factices. Sans cette variable, le mode réel est
sélectionné si au moins une clé du pool `HAI_API_KEY`, `HAI_API_KEY_2`, etc. et
`LINKUP_API_KEY` sont disponibles ; sinon l'application reste en mode démo.
`GLADIA_API_KEY` active la transcription réelle Gladia dans le mode réel.
L'API `/api/health` retourne le mode actif.

Lancement local sur un port distinct :

```sh
RUNAI_APP_HOST=127.0.0.1 RUNAI_APP_PORT=8002 .venv/bin/python -m runai.app
```

Les clés doivent être fournies par l'environnement d'exécution et ne doivent
jamais être écrites dans un fichier ni dans les journaux. Les traces de mission
sont enregistrées dans `traces/` par défaut.

## Questions et reprise

Les sessions H exposent l'outil asynchrone `ask_user(question, options)`.
L'application conserve les questions dans l'état de mission, les diffuse via
SSE et attend une réponse du portail ; après réponse, le résultat est renvoyé à
l'agent. Le délai maximal est configurable avec `RUNAI_QUESTION_TIMEOUT_S`
(600 secondes par défaut). En mode réel, il est plafonné à la durée maximale de
la session H moins 60 secondes. Il y a au plus deux questions par étape.

Le SDK H attache les définitions avec `AsyncClient.start_session(tools=...)`.
`HRun` consomme ensuite `AsyncSessionHandle.stream()` ; le flux asynchrone du
SDK exécute `_async_answer_tool_calls()` et renvoie les résultats à H sans
bloquer la boucle d'événements.

## Garde-fous du parcours Milan

- Inscription au Wizz Air Milano Marathon 2027 depuis le lien Njuko fourni par
  Linkup, avec le profil fictif et en invité. L'agent demande si le coureur a une
  Runcard ou un certificat médical d'effort ; il ne coche aucune case de santé
  et ne téléverse aucun document. Klikego est interdit.
- Hébergement Accor à Milan du 3 au 5 avril 2027, pour un adulte. Si la requête
  ne donne pas de budget, l'agent le demande avant toute recherche. Le serveur
  compare le prix total des deux nuits au double du budget par nuit et marque
  explicitement l'étape en échec si le tarif dépasse le plafond.
- Train aller-retour Paris–Milano sur trenitalia.com, les 3 et 5 avril 2027.
- Les agents demandent les informations manquantes au lieu de deviner, et
  s'arrêtent avant tout paiement, réservation, consentement ou soumission.
  Aucun captcha ni mécanisme anti-bot ne doit être contourné ; en cas de blocage,
  l'étape échoue explicitement avec le marqueur `BLOCAGE CAPTCHA/ANTI-BOT`.
- Les limites H par défaut sont de 60 étapes et 900 secondes par session ; elles
  sont réglables avec `RUNAI_H_MAX_STEPS` et `RUNAI_H_MAX_TIME_S`.
