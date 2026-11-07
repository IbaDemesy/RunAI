"""RunAI V2 contracts (G1): framing, missions and journeys. Additive; Race/StepResult unchanged.

Target HTTP API (E3 wiring, A1/A2 logic):

| Method | Route | Body → Response |
| --- | --- | --- |
| POST | /api/framings | FramingCreate → FramingSession (201) |
| GET | /api/framings/{id} | → FramingSession |
| POST | /api/framings/{id}/replies | FramingReply → FramingSession; 409 for stale revision |
| POST | /api/framings/{id}/confirm | FramingConfirm → MissionSnapshot; 409 if `assert_launchable` rejects; same key = same mission |
| POST | /api/framings/{id}/cancel | → FramingSession (cancelled) |
| GET | /api/missions/{id} | → MissionSnapshot |
| GET | /api/missions/{id}/events | SSE EventEnvelope; `Last-Event-ID` resumes without relaunching |
| POST | /api/missions/{id}/questions/{qid}/answer | HumanAnswer → MissionSnapshot; 409 for stale/duplicate answer |
| POST | /api/missions/{id}/cancel | → MissionSnapshot (cancelled) |
| GET | /api/missions/{id}/journey | → JourneyPlan (latest revision) |
| POST | /api/transcribe | audio → {"text"}; text goes through /replies with channel=voice |
| GET | /api/health | → {"mode", "providers": {"h"|"linkup"|"gladia": "ok"|"missing_key"|"error"}} |

No route starts a mission or H agent without confirmed framing.
"""

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
