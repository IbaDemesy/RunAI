# Phone demo

## Open the app

Open the deployment's Render HTTPS URL (for example,
`https://<service>.onrender.com/`) in Safari on iPhone or Chrome on Android.
Avoid in-app browsers. If Basic Auth is enabled, enter the username and password
supplied by the demo operator at the browser prompt. Never include credentials
in a URL or screenshot. A sleeping Render service may need time to wake up.

For a rehearsal without partner calls, run from the repository root:

```sh
RUNAI_MODE=demo RUNAI_APP_HOST=0.0.0.0 RUNAI_APP_PORT=8011 .venv/bin/python -m runai.app
```

Demo mode uses simulated providers, not live Gladia transcription. An HTTP LAN
address on a phone cannot use live microphone capture; use the HTTPS deployment
for voice. Check the visible mode before presenting: live mode can consume
partner credits, while demo results are fixtures rather than real availability.

## Microphone and live voice

Gladia live voice requires HTTPS, a configured live provider, and microphone
permission. Tap the microphone control and choose **Allow** at the prompt.
Grant the browser microphone access in the phone's system settings if requested.
If voice is unavailable, continue by typing; do not describe a simulated
transcript as live recognition.

To re-allow access after denying it:

- **iPhone / Safari:** open the page menu beside the address bar, then
  **Website Settings > Microphone > Allow** (labels vary by iOS version).
  Also check Safari's microphone permissions in Settings if needed.
- **Android / Chrome:** tap the site controls beside the address bar, open
  **Permissions > Microphone**, and allow or reset the permission. Also check
  **Settings > Apps > Chrome > Permissions > Microphone** on the phone.

Reload and tap the microphone again after changing permissions.

## Add to Home Screen

- **iPhone / Safari:** open the HTTPS URL, tap **Share > Add to Home Screen**,
  keep the name **RunAI**, then tap **Add**. Launch using the new icon.
- **Android / Chrome:** open the HTTPS URL, tap the three-dot menu, choose
  **Add to Home screen** (or **Install app**, if offered), and confirm. Chrome
  may offer a shortcut instead of installation without a service worker.

## 60-second demo: never pays

Prepare a simulated session with a supported fixture and a fictitious runner
profile before starting the clock. Never enter payment details.

1. **0–15 seconds — text framing with Holo:** type “Help me plan a Tokyo 10K
   trip in June 2028.” Answer Holo's questions about departure, dates, budget
   and travel needs. Explain that Holo structures the request.
2. **15–25 seconds — launch:** review the candidate and trip summary, select
   the event and launch the mission. Explain that this rehearsal uses fixtures,
   not live inventory.
3. **25–45 seconds — live step cards:** show registration, accommodation and
   transport progress. Expand a card to show the simulated agent's current
   step and activity, not a completed purchase.
4. **45–60 seconds — pre-payment halt:** show the stop-before-payment state
   and handoff summary. Say: “RunAI prepares the trip and stops before any
   payment or commitment. You review and take over; this demo never pays.”

If a run takes longer, show a prepared demo mission's cards rather than claiming
an unfinished run succeeded. Never confirm a purchase to finish the script.

## Known limits

- No offline mode and no service worker: network access is required, including
  after adding the icon to the home screen.
- Standalone behavior varies by browser and OS. External links may open a normal
  browser tab, Basic Auth may prompt again, and microphone permission may need
  to be granted separately. Return to Safari or Chrome if authentication or
  voice does not work from the home-screen icon.
- The manifest does not translate the existing interface; some screens still
  use the application's current language.
- Missions are held in memory and may disappear on server restart. Demo
  fixtures do not guarantee real event availability.
