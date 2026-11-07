# Spike axe 9 : recap PDF + .ics (+ mail Resend en option)

## Ce qui est prouvé
- **Modèle Pydantic `Recap`** (`models.py`) : course, essentiels du règlement, timeline, 3 missions (champs remplis, prix, capture avant paiement, lien pour finaliser, run H, validations humaines horodatées), profil du parcours, allures, check-list, sources.
- **Template Jinja2** (`templates/recap.html.j2`) qui reprend les 3 pages de la maquette ; profil du parcours généré en **SVG inline** (`svg_profile.py`). Vocabulaire « prêt », « à payer », « agent arrêté ici » ; jamais « réservé » (vérifié par test).
- **PDF** via Playwright `page.pdf()`, Chrome headless CLI (`--print-to-pdf`) ou WeasyPrint (`render.py`), comparés dans `bench.py`.
- **.ics RFC 5545** (`ics_export.py`) : retrait du dossard, départ, trajets aller/retour, check-in ; `TZID=Europe/Paris` + VTIMEZONE compacte (règle UE), alarmes, relu par 2 parseurs (icalendar 7.3 + vobject 0.9.9 `validate()`).
- **FastAPI** (`api.py`) : `GET /recap/{id}.pdf` (`?engine=playwright|weasyprint|chrome_cli`), `GET /recap/{id}.ics`, `GET /recap/{id}.html`, `POST /recap/{id}/send`, `POST /webhooks/resend`. Header `X-Gen-Ms`. Un Chromium est lancé une fois au démarrage.
- **Mail (sans clé, dry-run)** (`resend_mail.py`) : envoi Resend avec PDF + .ics en pièces jointes ; webhook `email.received` vérifié Svix → `GET /emails/receiving/{email_id}` → retrait de la citation → routage par mot-clé vers la mission → `POST /sessions/{id}/messages` (send_message H) précédé d'un garde-fou « ne paie rien ». Testé avec des transports httpx simulés.
- Deux recaps : `demo-nantes` (maquette, tout fictif) et `lisbonne-h` (hôtel + vol issus de **vraies sessions H** terminées, captures et chiffres lus via l'API H par `fetch_h_capture.py`).

## Relancer
```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
# Chrome : CHROME_PATH=/chemin/chrome, sinon `playwright install chromium`
python bench.py 5                      # -> out/bench.json, PDF, .ics, aperçus PNG
python -m pytest -q tests              # 15 tests
uvicorn api:app --port 8009            # puis /recap/demo-nantes.pdf, /recap/lisbonne-h.ics
HAI_API_KEY=... python fetch_h_capture.py <session_id> assets/x.png   # relit une session H (n'en crée pas)
```

## Résultats mesurés (VM Ubuntu 22.04, Python 3.10, Chrome for Testing 156, 7 nov. 2026)
Temps médians, `bench.py` N=5 (N=3 pour Chrome) :

| | HTML Jinja2 | .ics | Playwright (lancement compris) | Playwright navigateur chaud | Chrome CLI | WeasyPrint 70 |
|---|---|---|---|---|---|---|
| demo-nantes (3 p.) | 0,5 ms | 1,6 ms | 558 ms, 104 Ko | 132 ms | 341 ms, 167 Ko | 544 ms, 55 Ko |
| lisbonne-h (3 p., 2 captures PNG) | 1,3 ms | 1,6 ms | 655 ms, 227 Ko | 229 ms | 413 ms, 261 Ko | 424 ms, 247 Ko |

- Variabilité : un 2e passage (`bench.py 3`, celui de `out/bench.json`) donne Playwright 571 / 977 ms, chaud 183 / 337 ms, Chrome CLI 465 / 550 ms, WeasyPrint 646 / 438 ms, lancement Chromium 150 ms (VM partagée).
- Via HTTP (uvicorn, 3 appels) : `/recap/demo-nantes.pdf` 110–205 ms, `/recap/lisbonne-h.pdf` 203–254 ms, `.ics` 3–9 ms, `?engine=weasyprint` 499–955 ms ; id inconnu → 404.
- Lancement de Chromium par Playwright : 79 ms.
- .ics : 5 événements (Nantes) / 4 (Lisbonne), 2,5 Ko / 2,1 Ko, CRLF, lignes ≤ 75 octets, UID uniques, décalages vobject = zoneinfo (+02:00 en avril, +01:00 en mars). Les heures de Lisbonne sont converties en heure de Paris, l'heure locale est rappelée dans la description.
- Poids des deps (site-packages) : playwright 140 Mo + navigateur Chrome 403 Mo ; weasyprint 2,4 Mo + fontTools 27 Mo + pyphen 6,2 Mo + PIL 6,5 Mo + petits (≈ 43 Mo), plus Pango système (1.50 ici).
- Rendu : Chrome/Playwright fidèle à la maquette (même moteur que la maquette). WeasyPrint : rendu proche, mais il n'applique pas les classes CSS aux `<text>` du SVG inline (corrigé en mettant les attributs dans le SVG) et coupe différemment certains titres ; warning HarfBuzz-Subset sur Ubuntu 22.04.
- Sessions H relues (aucune créée par ce spike) : Accor `ea01ea80-ea2a-4efb-8885-8c123acc509a` (completed, 32 étapes, 1374 s API dont l'attente volontaire, ibis Lisboa Centro Liberdade 6–8 mars 2027, 185,41 €, page « Conclua a sua reserva ») ; TAP `d659ae18-6faa-4681-8e90-60bcee1d1db2` (completed, 29 étapes, 1356 s, TP 0441 ORY→LIS, 103,47 €, page passagers). Aucun paiement, aucune donnée personnelle saisie.

## Estimé / non vérifié
- Import réel dans Google Agenda / Apple Calendrier / Outlook : non testé (pas de compte) ; seuls 2 parseurs ont validé le fichier.
- Envoi Resend réel et webhook entrant réel : non testés (pas de clé) ; le format suit la doc Resend (pièces jointes base64, 40 Mo max après encodage).

## Clés et domaines pour activer le mail
- `RESEND_API_KEY` (re_…), `RESEND_FROM` sur un **domaine d'envoi vérifié** (SPF + DKIM, ex. `mail.runai.example`) ; sans domaine, Resend n'envoie qu'à l'adresse du compte depuis `onboarding@resend.dev`.
- Réception : domaine Resend `<id>.resend.app` (zéro DNS) ou sous-domaine perso avec **MX vers Resend** → `RESEND_INBOUND_DOMAIN` ; adresse de réponse `runai+{recap_id}@…`.
- Webhook `email.received` vers `https://<hôte public>/webhooks/resend` (tunnel type ngrok en démo) → `RESEND_WEBHOOK_SECRET` (whsec_…).
- `H_SEND_ENABLED=1` + `HAI_API_KEY` pour relayer vraiment. Attention : un send_message sur une session H **terminée la relance** (facturée, prend un slot du quota).
