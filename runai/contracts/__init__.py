"""Contrats V2 RunAI (G1) : cadrage, mission, séjour. Additifs ; Race/StepResult inchangés.

API HTTP cible (câblage E3, logique A1/A2) :

| Méthode | Route | Corps → Réponse |
| --- | --- | --- |
| POST | /api/framings | FramingCreate → FramingSession (201) |
| GET | /api/framings/{id} | → FramingSession |
| POST | /api/framings/{id}/replies | FramingReply → FramingSession ; 409 révision obsolète |
| POST | /api/framings/{id}/confirm | FramingConfirm → MissionSnapshot ; 409 si `assert_launchable` refuse ; même clé = même mission |
| POST | /api/framings/{id}/cancel | → FramingSession (cancelled) |
| GET | /api/missions/{id} | → MissionSnapshot |
| GET | /api/missions/{id}/events | SSE EventEnvelope ; `Last-Event-ID` reprend sans relancer |
| POST | /api/missions/{id}/questions/{qid}/answer | HumanAnswer → MissionSnapshot ; 409 périmée/doublon |
| POST | /api/missions/{id}/cancel | → MissionSnapshot (cancelled) |
| GET | /api/missions/{id}/journey | → JourneyPlan (dernière révision) |
| POST | /api/transcribe | audio → {"text"} ; le texte repasse par /replies avec channel=voice |
| GET | /api/health | → {"mode", "providers": {"h"|"linkup"|"gladia": "ok"|"missing_key"|"error"}} |

Il n'existe aucune route qui démarre une mission ou un agent H sans cadrage confirmé.
"""

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
