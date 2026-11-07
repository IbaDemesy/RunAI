# Récap du week-end (`runai/recap/`)

Transforme une mission terminée en **PDF A4** (à garder sur soi) et en **.ics** (à importer dans l'agenda). Le PDF affiche en tête « **0 € payé par RunAI** », la liste de **ce qui reste à faire par l'humain** (paiement, certificat, règlement… avec prix et lien vers la page où l'agent s'est arrêté), la timeline et les **sources**. Vocabulaire : « prêt, à payer », « agent arrêté ici », jamais « réservé ».

Porté depuis `spikes/recap_pdf_ics/` (branche `spike/recap_pdf_ics`), simplifié : un seul moteur PDF (Chrome headless en sous-processus), .ics écrit sans dépendance, pas de mail ni de profil altimétrique.

## API

```python
from runai.recap import recap_from_mission, render_html, render_pdf, render_ics, demo_recap

recap = recap_from_mission(
    race, profile, steps,                      # runai.models : Race, RunnerProfile, list[StepResult]
    recap_id=mission_id,
    voice_request="Je veux courir le marathon de Milan…",
    prices={StepKind.accommodation: 238.0},    # optionnel, remplace StepResult.price_eur
    options={StepKind.accommodation: ["Petit-déjeuner inclus"]},
    timeline=None,                             # None : retrait du dossard + départ déduits de `race`
    extra_timeline=[TimelineItem(...)],        # trains, check-in…
    checklist=["Pièce d'identité pour le dossard"],
    captures={StepKind.registration: png_bytes},  # dernière vue de l'agent, embarquée dans le PDF
)
html: str = render_html(recap)    # HTML autonome (CSS + captures en data: URI)
pdf: bytes = render_pdf(recap)    # Chrome headless, bloquant : anyio.to_thread.run_sync(render_pdf, recap)
ics: bytes = render_ics(recap)    # RFC 5545
```

- `recap_from_mission` garde la dernière étape de chaque type (inscription, hébergement, transport) et ignore `search`. L'action humaine dépend du `StopPoint` (ou de l'échec / de l'état en cours).
- Sources : `race.sources` (Linkup), `extra_sources`, puis la page atteinte par chaque agent (`StepResult.url`).
- Fuseau de la course déduit de `race.country` (IT → Europe/Rome…). Le .ics est écrit en `TZID=Europe/Paris` (paramètre `calendar_timezone`) avec une VTIMEZONE compacte à règle UE ; si le fuseau n'est pas à règle UE, heures en UTC. Heure inconnue → événement « journée ». Rappels : départ −12 h, ou `alarm_minutes`.
- Chrome : `RUNAI_CHROME` (ou `CHROME_PATH`), sinon `google-chrome`, `chromium`… dans le PATH. Absent → `PdfRenderError`.
- Dépendance ajoutée : `jinja2` (+ `markupsafe`).

## Démo

```bash
python -m runai.recap out/recap   # demo-milan.html / .pdf / .ics (Wizz Air Milano Marathon 2027, données fictives)
pytest -q tests/test_recap.py     # sans réseau ; le test PDF réel est sauté si Chrome est absent
```

## Mesures (VM Ubuntu, Python 3.12, Chrome for Testing 156, 7 nov. 2026)

| | temps | taille |
| --- | --- | --- |
| `recap_from_mission` (démo) | 0,2 ms | |
| `render_html` | 0,7 ms | 15 Ko |
| `render_ics` | 0,3 ms | 2,6 Ko, 5 événements |
| `render_pdf` (lancement de Chrome compris, 6 essais) | 342–462 ms | 129 Ko, 2 pages |

Le .ics de démo (et deux variantes : calendrier Europe/Lisbon, America/New_York) a été relu sans erreur par `icalendar` 7.0.3 et `vobject` 0.9.9 `validate()` (outils non ajoutés aux dépendances). Non testé : import réel dans Google Agenda, Apple Calendrier, Outlook. Le spike mesurait ~130 ms avec Playwright et un navigateur déjà lancé (non repris pour éviter 140 Mo de dépendance).

## Intégration proposée dans l'app (non implémentée)

- `GET /api/missions/{id}/recap.pdf` → `render_pdf` dans un thread, `Content-Disposition: attachment; filename=RunAI_recap_{id}.pdf`.
- `GET /api/missions/{id}/recap.ics` → `text/calendar; charset=utf-8`, `filename=week-end.ics`.
- `GET /api/missions/{id}/recap.html` → aperçu dans le portail.
- Point d'appel : `MissionService`, quand les trois agents sont arrêtés (`stopped_before_commitment` / `failed`), avec `race`, le profil et les `StepResult` ; captures = dernière observation H de chaque session.
- Bouton « Télécharger mon récap » sur le portail, à côté des actions humaines.
