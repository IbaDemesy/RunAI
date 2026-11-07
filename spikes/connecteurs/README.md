# Spike Axe D — Connecteurs utilisateur (mail, agenda, Strava/Garmin)

Prototypes Python autonomes, données **fictives** (Camille Martin, camille.martin@example.com). Aucune session H créée, aucun envoi réel, aucun appel Google/Strava/Resend live (pas de clé).

## Relancer

```bash
cd spikes/connecteurs
../../.venv/bin/python mail_recap.py                 # dry-run : out/recap.eml + validation
../../.venv/bin/python agenda_ics.py --niveau debutant  # week-ends libres + filtre courses + out/weekend.ics
../../.venv/bin/python strava_client.py              # mode fixture -> JSON profil + estimation
../../.venv/bin/python niveau.py fixtures/profil_declare.json
cd ../.. && .venv/bin/pytest -q spikes/connecteurs && .venv/bin/ruff check .
```

Envoi réel : `mail_recap.py --envoyer --backend resend|brevo|smtp --a camille.martin@example.com`.
Strava live : `strava_client.py --live` avec `STRAVA_ACCESS_TOKEN` (voir CGU ci-dessous : **ne pas brancher sur l'IA RunAI**).

## Résultats MESURÉS (7 nov. 2026, local)

- `pytest` : **7 passed** (0,12 s) ; `ruff check .` : OK.
- Mail dry-run : `recap.eml` **6 277 octets**, multipart/mixed → (text/plain + text/html) + `recap.pdf` (application/pdf) + `weekend.ics` (text/calendar, 5 VEVENT). Relu OK par `email` stdlib et par `icalendar` 6.1.3 (validateur indépendant). Payloads Resend/Brevo construits et testés (base64), **pas envoyés**.
- Agenda fixture (`agenda_camille.ics`, 9 VEVENT, récurrence WEEKLY INTERVAL=2 + UNTIL, journée entière, TZID, annulé, transparent) : 12 occupations, **16 week-ends libres / 29** entre le 09/11/2026 et le 31/05/2027 ; 1 warning (RRULE MONTHLY non gérée, signalée).
- Filtre courses (niveau débutant) : Milano Marathon 04/04/2027 **compatible** (20 sem. de prépa / 20 min.) ; 10 km Noël, Hyundai 7k et Vodafone 10K **conflit agenda** ; Semi fictif et Trail fictif **trop tôt**.
- Export `weekend.ics` (trajet aller, dossard, course, retour, hôtel, alarmes) : relu par notre parseur et par `icalendar` : 5 VEVENT.
- Inbound Resend → H : signature Svix (HMAC-SHA256) vérifiée, rejet corps modifié / horodatage > 5 min / session inconnue, extraction du texte sans citation — **testé avec mocks uniquement** (pas de clé Resend, aucun appel H).
- Strava fixture (37 activités dont 1 vélo ignoré, 20 détails avec `best_efforts`) : 36 sorties / 90 j, 2,8 sorties/sem., 30 km/sem., plus longue 16,3 km, meilleurs efforts 1K 5:02, 5K 26:05, 10K 52:59 → estimateur : **intermédiaire**, semi prédit 1:56:54 (Riegel 1,06).

## Verdicts

| Brique | Verdict | Effort restant (estimé) | Valeur démo | Valeur Computer Use |
|---|---|---|---|---|
| Mail récap PDF + .ics | **Faisable** (dry-run prouvé) | 1 h (clé + domaine) | Moyenne : « je reçois mon week-end » en fin de démo | **Nulle** (API) |
| Réponse mail → H `send_message` | Partiel (code + tests mocks) | 2 h (domaine inbound, webhook public) | Faible, risqué en live | Indirecte : pilote l'agent H, n'en est pas un |
| Agenda iCal privé / .ics importé | **Faisable** (prouvé localement) | 1 h (UI coller le lien) | Forte : « tes week-ends libres » filtre les courses | **Nulle** |
| Google Calendar API | Partiel (code non exécuté) | 2-3 h (projet GCP, consentement, test user) | Moyenne | Nulle |
| Strava API officielle | **Non faisable en l'état** pour RunAI (CGU) — code prêt | 1 h technique, bloqué juridiquement | Forte mais interdite | Nulle (et scraping exclu) |
| Garmin | Non faisable proprement | — | — | Nulle |

## Mail : comparaison

| | Resend | Brevo | SMTP Gmail |
|---|---|---|---|
| Config | `RESEND_API_KEY` (re_…), `MAIL_FROM` sur domaine vérifié (SPF/DKIM DNS) | `BREVO_API_KEY` (xkeysib-…), expéditeur validé (`MAIL_FROM`) | `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD` = mot de passe d'application 16 car. (2FA obligatoire) |
| Sans domaine | `onboarding@resend.dev` : envoi **uniquement vers l'adresse du compte**, sinon 403 | expéditeur simple validé possible, délivrabilité dégradée (gratuit 300/j : chiffre de sources secondaires, **à revalider**) | OK depuis l'adresse Gmail |
| Limites | Free 100/jour ; pièces jointes ≤ 40 Mo après base64 | voir ci-dessus | ~500/jour (compte perso) |
| Spam | faible si domaine DKIM/SPF/DMARC ; test via `delivered@resend.dev` | moyen sans domaine | moyen (Gmail→Gmail OK, risque ailleurs) |
| Inbound | `email.received` (webhook Svix, `whsec_…`) → l'API Receiving donne le corps | Inbound parsing (non testé) | non |

Recommandation démo : **Resend** + HTML `string.Template`/Jinja (React Email inutile en Python). Plan B sans domaine : SMTP Gmail d'un compte de l'équipe.
Inbound : `RESEND_WEBHOOK_SECRET`, `RESEND_API_KEY`, `HAI_API_KEY` ; Reply-To `runai+<session_id>@<domaine inbound>` ; le texte est relayé avec la consigne « ne jamais payer ni soumettre ».

## Agenda : comparaison

- **Lien iCal privé (« adresse secrète ») ou .ics** : zéro OAuth, parsing local (`agenda_ics.py`), lecture seule ; le lien est un secret (à ne pas logger). Ajout : fichier `.ics` importé (mail ou téléchargement). **Choix démo.**
- **Google Calendar API** : `agenda_google.py` ; scopes `calendar.freebusy` (lecture occupé/libre) + `calendar.app.created` (agenda « RunAI » séparé). Setup : projet GCP, écran de consentement, utilisateurs de test ; en mode Testing les refresh tokens expirent après 7 jours. Non exécuté (pas de client OAuth).
- **MCP Google Calendar** : `nspady/google-calendar-mcp` (MIT, ~1,2 k ★), `taylorwilsdon/google_workspace_mcp` (MIT, ~3,5 k ★) — même OAuth GCP à fournir, utile pour un assistant de bureau, pas pour le backend.
- **Microsoft Graph** `getSchedule` : `Calendars.ReadBasic` ; comptes Microsoft personnels non supportés pour cette API → hors démo.

## Strava / Garmin

- **MCP Strava officiel** `https://mcp.strava.com/mcp` : OAuth, lecture seule, propre compte, usage personnel (abonnement Strava). C'est **la seule voie autorisée** pour qu'une IA lise des données Strava, côté client de l'utilisateur (Claude/ChatGPT…), pas dans le backend RunAI.
- **MCP communautaire** `r-huijts/strava-mcp` (MIT, ~500 ★, dernier push juin 2026) : utilise l'API officielle → soumis à la même politique.
- **Politique API Strava (en vigueur 1er juin 2026)** : interdit l'usage des données de l'API pour développer/entraîner/évaluer **ou faire fonctionner** une application d'IA (context window, grounding, RAG). → `strava_client.py` reste un prototype ; à n'utiliser que si l'équipe obtient un accord écrit Strava. Comptes : app Strava (`STRAVA_CLIENT_ID`/`SECRET`, callback domain), scope `activity:read_all`, ~15 min de setup ; limite par défaut 100 req/15 min (lecture).
- **Garmin** : `cyberjunky/python-garminconnect` (MIT, ~3,3 k ★, actif) et `Taxuspt/garmin_mcp` (MIT, ~1,5 k ★, actif) : endpoints Garmin Connect **non officiels** (login identifiant/mot de passe), exposent activités, VO2max, prédictions de course. Non utilisés (non officiels, fragiles, identifiants réels). Programme officiel Garmin : Connect Developer Program (entreprises, sur demande) ; l'accès « personnel » à ses propres données existe mais n'autorise pas une app tierce.
- **Alternative retenue** : déclaration vocale (`fixtures/profil_declare.json`) → `niveau.py` (même format que la sortie Strava). Ou le coureur colle son résumé depuis le MCP officiel dans son propre assistant.

## Fichiers

`mail_recap.py`, `mail_inbound.py`, `minipdf.py` · `agenda_ics.py`, `agenda_google.py` · `strava_client.py`, `niveau.py` · `fixtures/` · `tests/`. Sorties dans `out/` (ignoré par git).
