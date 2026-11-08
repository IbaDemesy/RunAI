# English UI copy deck

## How to use / coverage

This is the source of truth for proposed English UI copy, not an instruction to change the current interface. The Translation cell may adopt this deck as its source. Keep keys stable when wording changes; never renumber existing file-scoped keys when adding a row. Reuse a key wherever the same meaning appears. Current FR cells preserve source literals, including leading and trailing spaces and interpolation expressions. Source copy may already be English.

Run `python docs/design/scripts/copy_coverage.py` from any directory. It compares extracted literals against only the current FR column and fails for missing app.js or live.html copy. The scanner is deliberately heuristic, not a JavaScript parser: comments, selectors, paths, identifiers and protocol values are excluded. Review dynamic templates and backend-generated copy manually when changing them. Companion files are inventoried below, but only app.js and live.html are enforced. Technical validation messages are included where they can surface as errors. Race identity and location fixture data remain upstream content, not translatable UI labels. Do not copy private profile data into this deck.

Maximum lengths are editorial character budgets for English rendered copy, not runtime truncation rules. Allow variable race names, URLs and user answers to wrap. Template proposals use named slots; substitute data, not JavaScript source. Never truncate safety instructions or next steps.

## Tone rules

- Speak like a runner planning a race: race, entry, start line, stay, journey, finish.
- Avoid developer jargon. An unavailable demo should say “Demo race not available — try one of the suggestions.” Internal fixture identifiers and session ids belong under “Technical details”.
- Use verbs for actions: “Start preparing”, not “Launch the search”.
- Use nouns for lanes: Registration / Stay / Transport.
- Introduce human questions with “Your turn”.
- Say “Prepared”, never “Booked”, for agent outcomes. Nothing is paid, submitted or reserved automatically.
- Errors explain what happened and the next safe step. Do not imply retrying commits anything.
- Use sentence case, concise buttons, and matching visible and accessible labels.

## Status vocabulary

The eight H lifecycle states in `runai/h/lifecycle.py::JobState` are distinct from the seven result states in `runai/models.py::StepStatus`.

| H lifecycle state | English label |
| --- | --- |
| queued | Waiting |
| running | In progress |
| paused | Paused |
| idle | Waiting for the next instruction |
| completed | Prepared |
| failed | Could not finish |
| cancelled | Cancelled |
| timed_out | Took too long |

Result states: `pending` → Waiting; `running` → In progress; `paused` → Paused; `waiting_for_user` → Your turn; `stopped_before_commitment` → Ready for you to finish; `completed` → Prepared; `failed` → Could not finish.

Mission states in `runai/app/mission.py::MissionStatus`: `searching` → Finding your race; `running` → Preparing your trip; `awaiting_human` → Prepared · finish on the official website (or Your turn when a question is open); `completed` → Prepared; `failed` → Could not finish; `cancelled` → Cancelled. A finished agent is not evidence of a reservation.

## Stop points

| Backend value | Heading | Guidance |
| --- | --- | --- |
| payment | Payment needs you | Review the price and pay yourself on the official website. |
| account_creation | Account creation needs you | Create or sign in to your account yourself on the official website. |
| health_declaration | Health declaration needs you | Read and complete health information yourself. RunAI cannot make a medical declaration for you. |
| consent | Consent needs you | Read the terms and decide yourself on the official website. |
| submission | Final submission needs you | Review all details before submitting yourself on the official website. |

## Partner attribution

Use exactly: “Found by Linkup”, “Framed by Holo”, “Voice by Gladia”, “H web-surfer-pro · step n/m”, “Self-repaired by Devin”. Show attribution only for work actually performed by that partner; replace n/m with observed counts, not invented progress. Preserve required map and data credits separately.

## H errors and next steps

Typed lifecycle codes come from `runai/h/lifecycle.py`. The H SDK also defines session error codes and answer outcomes, carried through `runai/h/runner.py::build_step_result` as error and outcome data. `answer_validation` is a session error code; `blocked` and `infeasible` are answer outcomes, not lifecycle exception codes. The installed `hai_agents.types.session_error_code` and `answer_outcome` definitions are the reference for those values.

| Kind | User-facing English |
| --- | --- |
| h_error | Preparation could not finish. Continue on the official website. |
| h_key_missing | The agent service is unavailable. Try again later or continue on the official website. |
| h_quota_saturated | All agents are busy. Wait a moment and try again. |
| h_anti_bot | The website needs a human check. The agent has stopped. Continue on the official website. |
| h_cancelled | Preparation cancelled. Review your trip before starting again. |
| h_timeout | The website took too long to respond. Continue on the official website or try again later. |
| environment_error | The browser could not open the website. Try again later or continue on the official website. |
| no_answer | The agent returned no result. Review the website yourself or try again. |
| timeout | The website took too long to respond. Continue on the official website or try again later. |
| insufficient_credit | The agent service cannot start right now. Try again later or continue on the official website. |
| internal | The agent service had a problem. Try again later or continue on the official website. |
| answer_validation | We could not verify the agent result. Review the details on the official website before continuing. |
| blocked | The agent could not continue on this website. Continue there yourself. |
| infeasible | The agent could not complete this request. Change your preferences or continue on the official website. |

Do not display raw exceptions, credentials or quota diagnostics in the main message. Keep redacted diagnostic information under Technical details. A human check is never bypassed.

## Formatting conventions

- Currency: €800; €80.50 when cents matter. Do not convert an unknown price to zero.
- Dates: Sat 11 Apr 2027 (shape example only; derive the weekday from the actual date). Use the trip timezone and show it when needed.
- Relative time: 4 s ago. Durations: 2 min 10 s.
- Distance: 21.1 km; elevation: +450 m. Use an en dash for ranges.
- Distinguish Verified, Estimated, Illustrative and Unknown. A verified source is not a booking.
- Keep unknown totals explicit; label partial totals and missing prices.

## Do not translate

Keep race names and official place names as supplied by their source. Preserve platform names including Njuko, Klikego, Booking, TAP, OpenStreetMap, Mapterhorn, MapLibre and EOX; partner and product names H, Holo, Linkup, Gladia, Devin and RunAI. Preserve legal attribution and licence text, URLs, and technical identifiers in Technical details.

## Copy inventory


### runai/app/static/app.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| app.001 |  Open the official site | Open the official website | Request / trip | 80 | Preserve source spacing; join fragments naturally. |
| app.002 |  Reload to try again without starting again. | Reload to try again. Your agents will not restart. | Request / trip | 80 | Preserve source spacing; join fragments naturally. |
| app.003 |  nuit | night | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.004 |  nuits | nights | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.005 | ). Try again. | ). Try again. | Request / trip | 32 | — |
| app.006 | Unable to refresh. Reload the page to resume without starting again. | We could not refresh your progress. Reload to reconnect without restarting. | Request / trip | 200 | — |
| app.007 | Live agent ·  | Agent live · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.008 | Enlarge | Expand | Request / trip | 32 | — |
| app.009 | Cancel request | Cancel request | Request / trip | 32 | — |
| app.010 | Cancel preparation | Cancel preparation | Request / trip | 32 | — |
| app.011 | Cancelled | Cancelled | Request / trip | 32 | — |
| app.012 | No agents started. | Preparation has not started. Confirm your plan first. | Request / trip | 80 | — |
| app.013 | No events received for this step. | No updates yet for this step. | Request / trip | 80 | — |
| app.014 | No H action received for this step. | Waiting for the first update from H. | Request / trip | 80 | — |
| app.015 | Bus | Coach | Request / trip | 32 | — |
| app.016 | Flight | Flight | Request / trip | 32 | — |
| app.017 | Budget | Budget | Request / trip | 32 | — |
| app.018 | Capture unavailable. Wait for the next observation or open H Replay. | Screenshot unavailable. Wait for the next update or open H replay. | Request / trip | 200 | — |
| app.019 | H captures update with observations; this is not a video stream. | H screenshots update as the agent works. This is not a video stream. | Request / trip | 200 | — |
| app.020 | Trip map | Trip map | Request / trip | 32 | — |
| app.021 | Map unavailable. The route is still available in the timeline. | Map unavailable. Follow your route in the trip timeline. | Request / trip | 80 | — |
| app.022 | What RunAI understood | Your plan so far | Request / trip | 32 | — |
| app.023 | This voice command is no longer active. | This voice command has expired. Speak again. | Request / trip | 80 | — |
| app.024 | This voice request is no longer active. | This voice request has expired. Speak again. | Request / trip | 80 | — |
| app.025 | Choose this race ·  | Choose this race · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.026 | Agent command not applied. Check their status. | Your voice command was not applied. Check the agents before trying again. | Request / trip | 200 | — |
| app.027 | Add to or correct your request | Add to or change your request | Request / trip | 80 | — |
| app.028 | Connection unavailable. Try again. | Connection unavailable. Check your connection and try again. | Request / trip | 80 | — |
| app.029 | Consent | Consent | Request / trip | 32 | — |
| app.030 | Continue manually on the official site | Continue on the official website | Request / trip | 80 | — |
| app.031 | Conversation updated. | Conversation updated. | Request / trip | 32 | — |
| app.032 | Correct ·  | Change · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.033 | Race | Race | Request / trip | 32 | — |
| app.034 | Race being prepared | Preparing your race | Request / trip | 32 | — |
| app.035 | Account creation | Account creation | Request / trip | 32 | — |
| app.036 | Race date | Race date | Request / trip | 32 | — |
| app.037 | Race date :  | Race date: | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.038 | Date unknown | Date not available | Request / trip | 32 | — |
| app.039 | Request accepted. | Request received. | Request / trip | 32 | — |
| app.040 | Request cancelled. No agents started. | Request cancelled. No agents were started. | Request / trip | 80 | — |
| app.041 | From  | From | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.042 | Latest H capture · step finished. | Last H screenshot · step finished. | Request / trip | 80 | — |
| app.043 | Latest H browser capture ·  | Latest H browser screenshot · | Request / trip | 80 | Preserve source spacing; join fragments naturally. |
| app.044 | Distance (km) | Distance (km) | Request / trip | 32 | — |
| app.045 | Tell me your next goal. I find the race, the bib, the hotel and the trip, and I stop before paying. | Tell me your next running goal. I will find your race, entry, stay and transport, and stop before payment. | Request / trip | 200 | — |
| app.046 | Demo | Demo | Request / trip | 32 | — |
| app.047 | Demo · demo | Demo · sample data | Request / trip | 32 | — |
| app.048 | Origin | Start | Request / trip | 32 | — |
| app.049 | Technical details | Technical details | Request / trip | 32 | — |
| app.050 | Waiting | Waiting | Request / trip | 32 | — |
| app.051 | Running | In progress | Request / trip | 32 | — |
| app.052 | Paused | Paused | Request / trip | 32 | — |
| app.053 | Sending… | Sending… | Request / trip | 32 | — |
| app.054 | Send | Send | Request / trip | 32 | — |
| app.055 | Send ·  | Send · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.056 | Estimated | Estimated | Request / trip | 32 | — |
| app.057 | Expired | Expired | Request / trip | 32 | — |
| app.058 | Explore | Explore | Request / trip | 32 | — |
| app.059 | Export this trip | Export this trip | Request / trip | 32 | — |
| app.060 | Agent history | Agent history | Request / trip | 32 | — |
| app.061 | Hotel | Stay | Request / trip | 32 | — |
| app.062 | Illustrative | Illustrative | Request / trip | 32 | — |
| app.063 | Unknown | Unknown | Request / trip | 32 | — |
| app.064 | Registration | Registration | Request / trip | 32 | — |
| app.065 | The request failed ( | We could not send your request ( | Request / trip | 80 | — |
| app.066 | Start the search | Start preparing | Request / trip | 32 | — |
| app.067 | The route received is invalid. Refresh and try again. | We could not load your route. Refresh and try again. | Request / trip | 80 | — |
| app.068 | Replay requires signing in to your H organization. | Sign in to your H organization to view the replay. | Request / trip | 80 | — |
| app.069 | Play | Play | Request / trip | 32 | — |
| app.070 | Microphone on. | Microphone on. | Request / trip | 32 | — |
| app.071 | Microphone off. | Microphone off. | Request / trip | 32 | — |
| app.072 | Transport mode | Transport type | Request / trip | 32 | — |
| app.073 | Mode unavailable. Check your connection before preparing your request. | We could not check the mode. Check your connection before starting. | Request / trip | 200 | — |
| app.074 | Mode not verified | Mode not verified | Request / trip | 32 | — |
| app.075 | Change something | Change something | Request / trip | 32 | — |
| app.076 | My first half marathon in October | My first half marathon in October | Request / trip | 80 | — |
| app.077 | My trip | My trip | Request / trip | 32 | — |
| app.078 | New request | Start a new request | Request / trip | 32 | — |
| app.079 | New value:  | New value: | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.080 | Nights | Nights | Request / trip | 32 | — |
| app.081 | Open | Open | Request / trip | 32 | — |
| app.082 | Open Explore to control the camera. | Open Explore to control the camera. | Request / trip | 80 | — |
| app.083 | Open in a tab | Open in a new tab | Request / trip | 32 | — |
| hero.title | Where do you want to run? | Where do you want to run? | Request / trip | 80 | — |
| app.085 | Payment | Payment | Request / trip | 32 | — |
| app.086 | Speak | Speak | Request / trip | 32 | — |
| app.087 | Pause | Pause | Request / trip | 32 | — |
| app.088 | Stop point:  | Stopped before: | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.089 | Missing item: Price unknown | Missing item: price unknown | Request / trip | 80 | — |
| app.090 | Preferences | Preferences | Request / trip | 32 | — |
| app.091 | Preparation in progress | Preparing your trip | Request / trip | 32 | — |
| app.092 | Preparation done · finish manually on the official site | Prepared · finish on the official website | Request / trip | 80 | — |
| app.093 | Prepared | Prepared | Request / trip | 32 | — |
| app.094 | Period | Date range | Request / trip | 32 | — |
| app.095 | Searching | Finding your race | Request / trip | 32 | — |
| app.096 | Reconnecting to updates… | Reconnecting to progress updates… | Request / trip | 80 | — |
| app.097 | Refused | Declined | Request / trip | 32 | — |
| app.098 | Replay · replay | Replay · recorded session | Request / trip | 80 | — |
| app.099 | Replay | Replay | Request / trip | 32 | — |
| app.100 | Replay H | H replay | Request / trip | 32 | — |
| app.101 | Unable to resume:  | We could not resume: | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.102 | RunAI is thinking | RunAI is thinking | Request / trip | 32 | — |
| app.103 | Shrink | Collapse | Request / trip | 32 | — |
| app.104 | Live | Live | Request / trip | 32 | — |
| app.105 | Live · live | Live · current data | Request / trip | 32 | — |
| app.106 | Try again | Try again | Request / trip | 32 | — |
| app.107 | Type or speak your answer… | Type or speak your answer… | Request / trip | 80 | — |
| app.108 | Answer accepted | Answer received | Request / trip | 32 | — |
| app.109 | Voice answer not applied. Check the current request. | Your voice answer was not applied. Check your updated plan before answering again. | Request / trip | 200 | — |
| app.110 | Voice revision expired. Check the updated request before answering. | Your plan changed while you were speaking. Review it before answering again. | Request / trip | 200 | — |
| app.111 | Not applicable | Not needed | Request / trip | 32 | — |
| app.112 | Session unavailable | Session unavailable | Request / trip | 32 | — |
| app.113 | If the view does not appear, open it in a tab. It expires when the run ends. | If the live view does not appear, open it in a new tab. It expires when the agent finishes. | Request / trip | 200 | — |
| app.114 | Source | Source | Request / trip | 32 | — |
| app.115 | Official source | Official source | Request / trip | 32 | — |
| app.116 | Mission status:  | Trip preparation: | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.117 | Updates interrupted. Reconnecting does not restart the agents. | Progress updates interrupted. Reconnecting will not restart the agents. | Request / trip | 200 | — |
| app.118 | Trip prepared · nothing committed automatically | Trip prepared · nothing committed automatically. | Request / trip | 80 | — |
| app.119 | Stop recording | Stop recording | Request / trip | 32 | — |
| app.120 | Page title unavailable | Page title unavailable | Request / trip | 32 | — |
| app.121 | Everything is ready. Check the summary before starting the search. | Your plan is ready. Review the summary before starting preparation. | Request / trip | 200 | — |
| app.122 | Train | Train | Request / trip | 32 | — |
| app.123 | Transcribing… | Turning your speech into text… | Request / trip | 80 | — |
| app.124 | Transport | Transport | Request / trip | 32 | — |
| app.125 | Local transport | Local transport | Request / trip | 32 | — |
| app.126 | Three agents will browse for you. They stop before any payment or final submission. | Three agents will prepare your trip. They stop before any payment or final submission. | Request / trip | 200 | — |
| app.127 | A spring marathon, leaving from Lyon | A spring marathon, travelling from Lyon | Request / trip | 80 | — |
| app.128 | A spring marathon, a city, an idea… | A spring marathon, a city, a goal… | Request / trip | 80 | — |
| app.129 | A mountain trail this summer | A mountain trail race this summer | Request / trip | 80 | — |
| app.130 | Anything to add? Write it here… | Anything to add? Type it here… | Request / trip | 80 | — |
| app.131 | City | City | Request / trip | 32 | — |
| app.132 | Watch the agent live | Watch the agent live | Request / trip | 32 | — |
| app.133 | Car | Car | Request / trip | 32 | — |
| app.134 | Plan your race through conversation | Your race starts with a conversation | Request / trip | 80 | — |
| app.135 | Your request, before starting | Review your plan before starting | Request / trip | 80 | — |
| app.136 | Your running goal | Your running goal | Request / trip | 32 | — |
| app.137 | Your answer ·  | Your turn · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.138 | Live agent view ·  | Agent live view · | Request / trip | 32 | Preserve source spacing; join fragments naturally. |
| app.139 | Verified | Verified | Request / trip | 32 | — |
| app.140 | inconnu | unknown | Request / trip | 32 | — |
| app.141 | inconnue | unknown | Request / trip | 32 | — |
| app.142 | Finish it yourself | Ready for you to finish | Request / trip | 32 | — |
| app.143 | Your turn to answer | Your turn | Request / trip | 32 | — |
| app.144 | Failed | Could not finish | Request / trip | 32 | — |
| app.145 | Trip screens | Trip views | Request / trip | 32 | — |
| app.146 | Edition | Edition | Request / trip | 32 | — |
| app.147 |  (current step) |  (current step) | Request / trip | 24 | — |
| app.148 | The previous conversation expired. Start a new request. | The previous conversation expired. Start a new request. | Request / trip | 80 | — |
| app.149 | Unable to resume the conversation:  | Unable to resume the conversation:  | Request / trip | 60 | — |

### runai/app/static/live.html

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| live.001 | Waiting for the agent… | Waiting for the agent… | Agent live | 32 | — |
| live.002 | Demo agent view | Demo agent view | Agent live | 32 | — |
| live.003 | Demo agent view · | Demo agent view · | Agent live | 32 | — |
| live.004 | stopped before commitment | stopped before commitment | Agent live | 80 | — |
| live.005 | waiting | waiting | Agent live | 32 | — |
| live.006 | in progress | in progress | Agent live | 32 | — |
| live.007 | paused | paused | Agent live | 32 | — |
| live.008 | prepared | prepared | Agent live | 32 | — |
| live.009 | could not finish | could not finish | Agent live | 32 | — |

### runai/app/static/index.html

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| index.001 | Mode en vérification | Checking mode | Shell header | 32 | — |
| index.002 | RunAI | RunAI | Shell header | 32 | — |
| index.003 | RunAI · Préparer ma course | RunAI · Prepare my race | Shell header | 32 | — |
| index.004 | RunAI, accueil | RunAI home | Shell header | 32 | — |

### runai/app/static/mock-api.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| mock_api.001 | Action inconnue. | That action is unavailable. Refresh and choose an available action. | Demo feedback | 200 | — |
| mock_api.002 | Flight | Flight | Demo feedback | 32 | — |
| mock_api.003 | Budget | Budget | Demo feedback | 32 | — |
| mock_api.004 | Choisissez une course proposée. | Choose one of the suggested races. | Demo feedback | 80 | — |
| mock_api.005 | Choix inconnu. | That choice is unavailable. Choose one of the current options. | Demo feedback | 80 | — |
| mock_api.006 | Clé de confirmation invalide. | We could not confirm your plan. Refresh and confirm again. | Demo feedback | 80 | — |
| mock_api.007 | Race | Race | Demo feedback | 32 | — |
| mock_api.008 | Race date | Race date | Demo feedback | 32 | — |
| mock_api.009 | Demande introuvable. | We could not find your request. Start a new request. | Demo feedback | 80 | — |
| mock_api.010 | Distance en km | Distance in km | Demo feedback | 32 | — |
| mock_api.011 | Origin | Start | Demo feedback | 32 | — |
| mock_api.012 | Fixtures de démonstration indisponibles. Vérifiez leur montage. | Demo race not available — try one of the suggestions. | Demo feedback | 80 | — |
| mock_api.013 | Information inconnue. | That detail is unavailable. Check your plan and try again. | Demo feedback | 80 | — |
| mock_api.014 | Mission déjà lancée. | Preparation has already started. Open your progress to continue. | Demo feedback | 80 | — |
| mock_api.015 | Mission introuvable. | We could not find this trip. Open your latest request or start a new one. | Demo feedback | 200 | — |
| mock_api.016 | Nights | Nights | Demo feedback | 32 | — |
| mock_api.017 | Preferences | Preferences | Demo feedback | 32 | — |
| mock_api.018 | Préparé, à valider sur le site officiel. | Prepared · review on the official website. | Demo feedback | 80 | — |
| mock_api.019 | Period | Date range | Demo feedback | 32 | — |
| mock_api.020 | Question expirée ou déjà traitée. | This question has expired or was already answered. Check for a new question. | Demo feedback | 200 | — |
| mock_api.021 | Question obsolète. | This question has changed. Answer the latest question. | Demo feedback | 80 | — |
| mock_api.022 | Route de démonstration inconnue. | This demo is unavailable. Try one of the suggested races. | Demo feedback | 80 | — |
| mock_api.023 | Réponse invalide. | We could not use that answer. Check the question and try again. | Demo feedback | 80 | — |
| mock_api.024 | Résumé obsolète. | Your plan has changed. Review the latest summary before confirming. | Demo feedback | 200 | — |
| mock_api.025 | Révision obsolète. | Your plan has changed. Refresh before continuing. | Demo feedback | 80 | — |
| mock_api.026 | Transport | Transport | Demo feedback | 32 | — |
| mock_api.027 | Une demande existe déjà. | You already have a request. Open it to continue. | Demo feedback | 80 | — |
| mock_api.028 | City | City | Demo feedback | 32 | — |
| mock_api.029 | Edition | Edition | Demo feedback | 32 | — |

### runai/app/static/journey-view.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| journey_view.001 | Carte indisponible ; timeline disponible. | Map unavailable. Use the trip timeline. | Request / trip | 80 | — |
| journey_view.002 | MapLibre indisponible | Map unavailable. Use the trip timeline. | Request / trip | 80 | — |
| journey_view.003 | © OpenStreetMap contributors | © OpenStreetMap contributors | Request / trip | 80 | — |

### web/voice/voice-input.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| voice_input.001 | Audio vide | No audio recorded. Try speaking again or type your answer. | Voice | 80 | — |
| voice_input.002 | Cadrage vocal non connecté | Voice is unavailable for this request. Type your answer instead. | Voice | 80 | — |
| voice_input.003 | Contrôle des agents non connecté | Voice controls are unavailable. Use the preparation controls instead. | Voice | 200 | — |
| voice_input.004 | Erreur microphone ou transcription | We could not hear you. Check your microphone and try again, or type your answer. | Voice | 200 | — |
| voice_input.005 | Microphone non pris en charge ; utilisez le texte. | Your browser does not support the microphone. Type your answer instead. | Voice | 200 | — |
| voice_input.006 | Permission microphone refusée | Microphone access was denied. Allow access in your browser or type your answer. | Voice | 200 | — |
| voice_input.007 | Révision de cadrage absente | We could not match your voice answer to this plan. Refresh and try again. | Voice | 200 | — |
| voice_input.008 | Transcription impossible (${response.status}) : ${detail} | We could not turn your speech into text. Try again or type your answer. | Voice | 200 | Dynamic slot; preserve data, not implementation. |
| voice_input.009 | Transcription trop longue pour le cadrage | That recording is too long. Try a shorter answer or type it instead. | Voice | 200 | — |
| voice_input.010 | Transcription vide | We did not catch any words. Try speaking again or type your answer. | Voice | 200 | — |
| voice_input.011 | Vue du séjour non connectée | Trip voice controls are unavailable. Open your trip and try again. | Voice | 200 | — |

### web/flyover/flyover.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| flyover.001 |  Ouvrez la page via un serveur local (voir README) ou choisissez un fichier. | Choose a route file to continue. | Explore | 80 | Preserve source spacing; join fragments naturally. |
| flyover.002 |  · ${Math.round(here.ele)} m | · ${Math.round(here.ele)} m | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| flyover.003 | ${Math.round(d / 1000)} km | ${Math.round(d / 1000)} km | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| flyover.004 | ${Math.round(ele)} m | ${Math.round(ele)} m | Explore | 32 | Dynamic slot; preserve data, not implementation. |
| flyover.005 | ${Math.round(track.minEle)}–${Math.round(track.maxEle)} m | ${Math.round(track.minEle)}–${Math.round(track.maxEle)} m | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| flyover.006 | (Contains modified Copernicus Sentinel data 2020), CC BY-NC-SA 4.0 | (Contains modified Copernicus Sentinel data 2020), CC BY-NC-SA 4.0 | Explore | 200 | — |
| flyover.007 | <a href='https://s2maps.eu' target='_blank'>Sentinel-2 cloudless 2020</a> by EOX IT Services GmbH  | <a href='https://s2maps.eu' target='_blank'>Sentinel-2 cloudless 2020</a> by EOX IT Services GmbH | Explore | 200 | Preserve source spacing; join fragments naturally. |
| flyover.008 | Arrivée | Finish | Explore | 32 | — |
| flyover.009 | Origin | Start | Explore | 32 | — |
| flyover.010 | Départ / Arrivée | Start / Finish | Explore | 32 | — |
| flyover.011 | Fichier illisible : ${error.message} | We could not read this route file. Choose another GPX or KML file. | Explore | 200 | Dynamic slot; preserve data, not implementation. |
| flyover.012 | Impossible de charger ${url} : ${error.message}.${hint} | We could not load the route. Check your connection or choose a route file. | Explore | 200 | Dynamic slot; preserve data, not implementation. |
| flyover.013 | MapLibre GL JS n'a pas pu être chargé (réseau ?). | We could not load the map. Check your connection or use the trip timeline. | Explore | 200 | — |
| flyover.014 | Mapterhorn (z${TERRAIN_SAMPLE_ZOOM}) | Mapterhorn (z${TERRAIN_SAMPLE_ZOOM}) | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| flyover.015 | Parcours sans nom | Unnamed route | Explore | 32 | — |
| flyover.016 | Pas d'altitude dans le fichier : lecture du relief Mapterhorn… | No elevation in this file. Loading terrain from Mapterhorn… | Explore | 80 | — |
| flyover.017 | ≈ +${Math.round(track.gain)} m / −${Math.round(track.loss)} m | ≈ +${Math.round(track.gain)} m / −${Math.round(track.loss)} m | Explore | 80 | Dynamic slot; preserve data, not implementation. |

### web/flyover/journey-contract.js

No user-facing literals found; contract identifiers are not UI copy.

### web/flyover/journey-data.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| journey_data.001 | Invalid JourneyPlan: ${errors.join("; ")} | We could not read your trip. Reload to try again. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_data.002 | Invalid geometry_status: ${geometryStatus} | Route details are invalid. Reload your trip. | Explore | 80 | Dynamic slot; preserve data, not implementation. |

### web/flyover/journey-fallback.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| journey_fallback.001 |  (${CONFIDENCE[line.money.confidence] &#124;&#124; "non vérifié"}, collecte : ${line.money.collected_at}) | ({confidence}, checked {collected_at}) | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.002 | ${budget.complete ? "Total renseigné" : "Total partiel"} : ${moneyText({ amount: budget.known_total, currency: budget.currency })} | {total_label}: {amount}. Use Total or Partial total as appropriate. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.003 | ${segment.duration_min == null ? "Durée inconnue" : `${segment.duration_min} min`} — ${moneyText(segment.cost)} | {duration} — {cost}. Use Duration unknown when missing. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.004 | ${timeText(stop.local_time, stop.timezone)}${stop.coords ? "" : " — Localisation non renseignée"} | {local_time} · {timezone}. Show Location not available when missing. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.005 | Approximatif : géométrie estimée, à vérifier. | Approximate route · check before travelling. | Explore | 80 | — |
| journey_fallback.006 | Aucune source fournie : informations à vérifier. | No source provided. Check these details before travelling. | Explore | 80 | — |
| journey_fallback.007 | Budget | Budget | Explore | 32 | — |
| journey_fallback.008 | Budget du séjour | Trip budget | Explore | 32 | — |
| journey_fallback.009 | Carte indisponible : le séjour reste lisible sans carte. Utilisez les chapitres et les liens manuels. | Map unavailable. Use the trip chapters and website links to continue. | Explore | 200 | — |
| journey_fallback.010 | Chapitre : ${chapter.label}. ${STATUS[chapter.status] &#124;&#124; "À compléter"}. | Chapter: {chapter_label}. {status}. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.011 | Chapitre inconnu : ${id} | This chapter is unavailable. Choose another chapter. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.012 | Chapitre précédent | Previous chapter | Explore | 32 | — |
| journey_fallback.013 | Chapitre suivant | Next chapter | Explore | 32 | — |
| journey_fallback.014 | Chapitres du séjour | Trip chapters | Explore | 32 | — |
| journey_fallback.015 | Charger journey-contract.js avant le repli du séjour. | We could not open your trip. Reload to try again. | Explore | 80 | — |
| journey_fallback.016 | Choisissez un séjour pour afficher sa timeline. | Choose a trip to see its timeline. | Explore | 80 | — |
| journey_fallback.017 | Consulter le site manuellement | Open the website yourself | Explore | 80 | — |
| journey_fallback.018 | Race | Race | Explore | 32 | — |
| journey_fallback.019 | Course : km ${value.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}. ${GEOMETRY[segment.geometry_status]} | Race: km {distance}. {route_confidence} | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.020 | Depuis ${plan.origin_public} — ${plan.date_range ? plan.date_range.join(" au ") : "Dates à préciser"} — fuseau du séjour : ${plan.timezone} | From {origin} — {date_range} — trip timezone: {timezone}. Use Dates needed when missing. | Explore | 200 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.021 | Distance invalide | That distance is unavailable. Choose a distance on the route. | Explore | 80 | — |
| journey_fallback.022 | Distance non disponible : aucun tracé de course exploitable dans cette vue. | No race route is available here. Choose a trip chapter instead. | Explore | 80 | — |
| journey_fallback.023 | Démonstration : données fictives | Demo · sample data | Explore | 32 | — |
| journey_fallback.024 | Départ : ${timeText(segment.departure, segment.timezone)} ; arrivée : ${timeText(segment.arrival, segment.timezone)} | Departure: {departure}; arrival: {arrival} | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.025 | Horaire non renseigné | Time not available | Explore | 32 | — |
| journey_fallback.026 | Illustratif : liaison indicative, pas un itinéraire à suivre. | Illustrative connection · not a route to follow. | Explore | 80 | — |
| journey_fallback.027 | Informations non renseignées. À compléter avec vous. | Details missing. We will fill them in with you. | Explore | 80 | — |
| journey_fallback.028 | JourneyPlan invalide : ${errors.join(", ")} | We could not read your trip. Reload to try again. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.029 | Lecture de la timeline en pause. | Trip playback paused. | Explore | 32 | — |
| journey_fallback.030 | Lecture de la timeline. Pause arrête uniquement cette vue, pas les agents. | Playing your trip. Pausing this view does not pause the agents. | Explore | 80 | — |
| journey_fallback.031 | Lire la timeline | Play trip timeline | Explore | 32 | — |
| journey_fallback.032 | Légende des tracés | Route key | Explore | 32 | — |
| journey_fallback.033 | Mon séjour, étape par étape | My trip, step by step | Explore | 32 | — |
| journey_fallback.034 | Mouvement réduit : navigation manuelle par chapitre. | Reduced motion on. Choose a chapter to move through your trip. | Explore | 80 | — |
| journey_fallback.035 | Mouvement réduit : utilisez les chapitres sans lecture automatique. | Reduced motion on. Use chapters without autoplay. | Explore | 80 | — |
| journey_fallback.036 | Non automatisé | Manual step | Explore | 32 | — |
| journey_fallback.037 | Ouvrir le site manuellement | Open the website yourself | Explore | 80 | — |
| journey_fallback.038 | Pause | Pause | Explore | 32 | — |
| journey_fallback.039 | Plafond : ${moneyText({ amount: budget.cap, currency: budget.currency })}. ${budget.over_cap === true ? "Plafond dépassé." : budget.over_cap === false ? "Total renseigné sous le plafond." : "Plafond non vérifiable avec les prix manquants."} | Budget limit: {cap}. {comparison}. Use Over budget, Known total within budget, or Cannot check the limit with missing prices. | Explore | 200 | Dynamic slot; preserve data, not implementation. |
| journey_fallback.040 | Postes manquants non comptés comme zéro. Le total final reste inconnu. | Missing prices are not counted as zero. The final total is still unknown. | Explore | 200 | — |
| journey_fallback.041 | Prix inconnu | Price unknown | Explore | 32 | — |
| journey_fallback.042 | Préparation automatisée, rien de réservé | Prepared by agents · nothing booked | Explore | 80 | — |
| journey_fallback.043 | Préparé ne signifie pas réservé. Aucune action engageante depuis cette vue. | Prepared does not mean booked. This view cannot make commitments for you. | Explore | 200 | — |
| journey_fallback.044 | Renseigné | Details available | Explore | 32 | — |
| journey_fallback.045 | Replay : enregistrement, pas du direct | Replay · recorded, not live | Explore | 80 | — |
| journey_fallback.046 | Réel (live) | Live · current data | Explore | 32 | — |
| journey_fallback.047 | Source | Source | Explore | 32 | — |
| journey_fallback.048 | Sources et attributions | Sources and credits | Explore | 32 | — |
| journey_fallback.049 | Séjour disponible sans carte. Choisissez un chapitre. | Your trip is available without the map. Choose a chapter. | Explore | 80 | — |
| journey_fallback.050 | Séjour indisponible : données invalides. Rechargez le séjour. | We could not read your trip. Reload to try again. | Explore | 80 | — |
| journey_fallback.051 | Séjour indisponible : rechargez ses données. | Your trip is unavailable. Reload to try again. | Explore | 80 | — |
| journey_fallback.052 | Séjour sans carte | Trip without a map | Explore | 32 | — |
| journey_fallback.053 | Tracé indisponible : aucun itinéraire inventé. | Route unavailable. We will not invent one. | Explore | 80 | — |
| journey_fallback.054 | Train | Train | Explore | 32 | — |
| journey_fallback.055 | Local transport | Local transport | Explore | 32 | — |
| journey_fallback.056 | Vue sans fond de carte : aucune tuile chargée. Les crédits de la carte, si utilisée, restent à afficher dans sa vue. | Map-free view. Map credits appear in the map view when available. | Explore | 200 | — |
| journey_fallback.057 | Vérifié : géométrie sourcée, pas une réservation. | Verified route source · not a booking. | Explore | 80 | — |
| journey_fallback.058 | estimé | estimated | Explore | 32 | — |
| journey_fallback.059 | non vérifié | not verified | Explore | 32 | — |
| journey_fallback.060 | vérifié | verified | Explore | 32 | — |
| journey_fallback.061 | À compléter | Details needed | Explore | 32 | — |
| journey_fallback.062 | À finaliser manuellement | Finish yourself | Explore | 32 | — |

### web/flyover/journey-player.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| journey_player.001 | Aucun JourneyPlan chargé. | No trip loaded. Open a trip to continue. | Explore | 80 | — |
| journey_player.002 | Aucun chapitre dans le JourneyPlan. | No trip chapters available. Reload your trip. | Explore | 80 | — |
| journey_player.003 | Chapitre ${chapterId} non affichable : aucune position sourcée. | This chapter has no verified location. Choose another chapter. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_player.004 | Chapitre inconnu : ${chapterId} | This chapter is unavailable. Choose another chapter. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_player.005 | Kilomètre invalide : ${km} | That kilometre is unavailable. Choose a point on the race route. | Explore | 80 | Dynamic slot; preserve data, not implementation. |
| journey_player.006 | Tracé de course non disponible : pas de positionnement au km. | Race route unavailable. Choose a trip chapter instead. | Explore | 80 | — |
| journey_player.007 | Vue détruite. | This view has closed. Reopen your trip to continue. | Explore | 80 | — |

### web/flyover/route.js

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| route.001 | Aucun tracé exploitable : il faut au moins deux points (trkpt, rtept ou LineString). | This file has no usable route. Choose a GPX or KML file with at least two route points. | Explore | 200 | — |

### runai/app/fakes.py

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| fakes.001 |  Consignes appliquées :  | Instructions followed: | Demo preparation | 32 | Preserve source spacing; join fragments naturally. |
| fakes.002 |  Réponses utilisateur :  | Your answers: | Demo preparation | 32 | Preserve source spacing; join fragments naturally. |
| fakes.003 |  nuits | nights | Demo preparation | 32 | Preserve source spacing; join fragments naturally. |
| fakes.004 | Aller-retour sélectionné ; arrêt avant le paiement. | Return journey selected · stopped before payment. | Demo preparation | 80 | — |
| fakes.005 | Chambre sélectionnée pour la veille de la course ; arrêt avant le paiement. | Room selected for the night before the race · stopped before payment. | Demo preparation | 200 | — |
| fakes.006 | Choix de l'aller la veille de la course | Choosing outbound travel for the day before the race | Demo preparation | 80 | — |
| fakes.007 | Choix de la distance | Choosing your race distance | Demo preparation | 80 | — |
| fakes.008 | Choix du retour après l'arrivée | Choosing return travel after the finish | Demo preparation | 80 | — |
| fakes.009 | Consigne reçue : «  | Instruction received: | Demo preparation | 32 | Preserve source spacing; join fragments naturally. |
| fakes.010 | Découverte | First-timer | Demo preparation | 32 | — |
| fakes.011 | Démo —  | Demo — | Demo preparation | 32 | Preserve source spacing; join fragments naturally. |
| fakes.012 | Expo course, la veille (donnée factice) | Race expo, the day before · sample data | Demo preparation | 80 | — |
| fakes.013 | Filtre : annulation gratuite | Filtering for free cancellation | Demo preparation | 80 | — |
| fakes.014 | Fixture démo, pas un événement réel | Demo race · not a real event | Demo preparation | 80 | — |
| fakes.015 | Formulaire pré-rempli ; arrêt avant la case « J'accepte le règlement ». | Form prepared · stopped before accepting the race rules. | Demo preparation | 80 | — |
| fakes.016 | Lisbon 10K (démo) | Lisbon 10K · demo | Demo preparation | 32 | — |
| fakes.017 | Ouverture de la page d'inscription | Opening the registration page | Demo preparation | 80 | — |
| fakes.018 | Page de paiement atteinte | Payment page reached · waiting for you | Demo preparation | 80 | — |
| fakes.019 | Page « Règlement et certificat médical » atteinte | Race rules and health documents page reached · waiting for you | Demo preparation | 80 | — |
| fakes.020 | Pas de fixture démo pour cette ville | Demo race not available — try one of the suggestions. | Demo preparation | 80 | — |
| fakes.021 | Performance | Performance | Demo preparation | 32 | — |
| fakes.022 | Piazza Duomo (donnée factice) | Piazza Duomo · sample data | Demo preparation | 80 | — |
| fakes.023 | Praça do Comércio (donnée factice) | Praça do Comércio · sample data | Demo preparation | 80 | — |
| fakes.024 | Préférence horaire pour le trajet confirmé (démo) ? | Your turn · what time would you prefer to travel? (Demo) | Demo preparation | 80 | — |
| fakes.025 | Quel sas souhaitez-vous examiner (démo) ? | Your turn · which start wave would you like to explore? (Demo) | Demo preparation | 80 | — |
| fakes.026 | Quel temps visez-vous ? (pour le sas de départ) | Your turn · what finish time are you aiming for? This helps choose your start wave. | Demo preparation | 200 | — |
| fakes.027 | Recherche d'hôtels près du départ | Finding stays near the start | Demo preparation | 80 | — |
| fakes.028 | Recherche d'un aller-retour | Finding return travel | Demo preparation | 32 | — |
| fakes.029 | Saisie de l'e-mail et de la date de naissance | Entering email and date of birth | Demo preparation | 80 | — |
| fakes.030 | Saisie des coordonnées du voyageur (profil fictif) | Entering traveller details · sample profile | Demo preparation | 80 | — |
| fakes.031 | Saisie du nom et du prénom (profil fictif) | Entering first and last name · sample profile | Demo preparation | 80 | — |
| fakes.032 | Saisie du passager (profil fictif) | Entering passenger details · sample profile | Demo preparation | 80 | — |
| fakes.033 | Source factice | Sample source | Demo preparation | 32 | — |
| fakes.034 | Sélection de l'hôtel le plus proche du départ | Choosing the closest stay to the start | Demo preparation | 80 | — |
| fakes.035 | Tokyo 10K (démo) | Tokyo 10K · demo | Demo preparation | 32 | — |
| fakes.036 | Village marathon, la veille (donnée factice) | Race village, the day before · sample data | Demo preparation | 80 | — |
| fakes.037 | après-midi | afternoon | Demo preparation | 32 | — |

### runai/h/narrate.py

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| narrate.001 | Attend votre réponse :  | Your turn: | Agent progress | 32 | Preserve source spacing; join fragments naturally. |
| narrate.002 | L'agent n'a pas pu terminer cette étape. Vous pouvez la faire vous-même depuis le site officiel. | The agent could not finish this step. Continue on the official website. | Agent progress | 200 | — |
| narrate.003 | Le service d'agents est indisponible pour le moment. | The agent service is unavailable. Try again later or continue on the official website. | Agent progress | 200 | — |
| narrate.004 | Le site a mis trop de temps à répondre. Vous pouvez reprendre cette étape vous-même. | The website took too long to respond. Continue this step on the official website. | Agent progress | 200 | — |
| narrate.005 | Ouverture du navigateur… | Opening the website… | Agent progress | 32 | — |
| narrate.006 | Prêt : à finaliser vous-même sur le site officiel | Prepared · finish on the official website | Agent progress | 80 | — |
| narrate.007 | Site protégé par un captcha : l'agent s'est arrêté. Finissez cette étape vous-même sur le site officiel. | The website needs a human check. The agent has stopped. Continue on the official website. | Agent progress | 200 | — |

### Additional fragments and demo choices

| key | current FR | proposed EN | context/screen | max length | notes |
| --- | --- | --- | --- | --- | --- |
| app.link_new_tab |  (new tab) |  (new tab) | Request / trip | 80 | Preserve dynamic data and source spacing. |
| app.thinking | RunAI is searching for you… | RunAI is searching for you… | Request / trip | 80 | Preserve dynamic data and source spacing. |
| app.budget_suffix |  € max |  maximum | Request / trip | 80 | Preserve dynamic data and source spacing. |
| app.partner_gladia | Voice by Gladia solaria-1 · live | Voice by Gladia solaria-1 · live | Request / trip | 48 | Partner attribution; keep product names. |
| app.voice_demo | Demo voice | Demo voice | Voice | 48 | Simulated transcription. |
| app.voice_replay | Recorded voice | Recorded voice | Voice | 48 | Recorded transcription. |
| app.voice_unknown | Voice input | Voice input | Voice | 48 | No provider attribution without evidence. |
| journey_fallback.walk | Marche | Walk | Explore | 80 | Preserve dynamic data and source spacing. |
| journey_fallback.flight | Flight | Flight | Explore | 80 | Preserve dynamic data and source spacing. |
| journey_fallback.partial | Partiel | Partial | Explore | 80 | Preserve dynamic data and source spacing. |
| journey_fallback.illustrative | illustratif | illustrative | Explore | 80 | Preserve dynamic data and source spacing. |
| journey_fallback.new_tab | ${label} (nouvel onglet) | {label} (new tab) | Explore | 80 | Preserve dynamic data and source spacing. |
| fakes.morning | matin | morning | Demo preparation | 80 | Preserve dynamic data and source spacing. |
| fakes.under_time | moins de 3h30 | under 3 h 30 min | Demo preparation | 80 | Preserve dynamic data and source spacing. |
| fakes.mid_time | 3h30–4h | 3 h 30 min–4 h | Demo preparation | 80 | Preserve dynamic data and source spacing. |
| fakes.over_time | plus de 4h | over 4 h | Demo preparation | 80 | Preserve dynamic data and source spacing. |
| narrate.website | Sur  | On {host} | Agent progress | 80 | Show only the public hostname and page title; preserve source spacing. |
| flyover.file_source | fichier (GPX/KML) | Route file (GPX/KML) | Explore | 32 | Source label. |
| framing.more_details | Tell me a little more about your plans. | Tell me a little more about your running goal. | Request framing | 80 | Prompt when more details are needed. |
| stay.export_action | Export  | Export  | Trip export | 32 | Append the format name; preserve trailing space. |
| framing.not_needed |  : not applicable | : not needed | Request framing | 32 | Append to the detail label. |
