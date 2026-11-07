import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from runai.app.mission import Mission
from runai.app.replay import ReplayTrace
from runai.app.server import build_demo_service, create_app
from runai.contracts import load_fixture
from runai.contracts.framing import FramingError, FramingSession, FramingStatus
from runai.contracts.journey import JourneyPlan
from runai.contracts.mission import EventEnvelope, MissionSnapshot
from runai.framing.launch import plan_launch
from runai.models import StepKind, StepResult, TraceEvent
from runai.planning import recap_adapter
from runai.tracing import TraceWriter

SENTINEL = "FAKE-OUTPUT-ONLY-SENTINEL-123"
SURFACES = ["live", "step", "snapshot", "snapshot_api", "sse", "journey", "html", "ics", "pdf",
            "trace", "replay", "http_error", "validation_error", "transcription", "transcription_error",
            "framing", "framing_error", "health"]


@pytest.mark.parametrize("surface", SURFACES)
def test_provider_diagnostics_are_redacted_at_all_output_boundaries(surface, monkeypatch, tmp_path):
    monkeypatch.setenv("HAI_API_KEY_2", SENTINEL)
    nested = {"provider_diagnostics": {"message": SENTINEL, "nested": [{SENTINEL: SENTINEL}]}}
    step = StepResult(kind=StepKind.transport, status="failed", h_session_id="parent-probe-session")
    step.data.update(nested)
    step.summary = SENTINEL
    event = TraceEvent(source="provider", type="diagnostic", message=SENTINEL,
                       data={"session_id": "parent-probe-session", **nested})
    session = FramingSession.model_validate(load_fixture("framing_ready.json"))
    session.status = FramingStatus.confirmed
    session.confirmed_revision = session.revision
    launch = plan_launch(session)
    mission = Mission(id="output-probe", query="Synthetic probe", status="failed", plan=launch,
                      steps={StepKind.transport: step}, events=[event])
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    service.missions[mission.id] = mission
    plan = JourneyPlan.model_validate(load_fixture("journey_train.json"))
    plan.mission_id = mission.id
    plan.warnings.append(SENTINEL)
    plan.stops[0].label = SENTINEL
    mission.journey = plan
    service._recaps[(mission.id, plan.revision)] = recap_adapter.recap_from_journey(plan)
    app = create_app(service)
    route = f"/api/missions/{mission.id}"

    if surface == "step":
        output = step.model_dump_json()
    elif surface == "snapshot":
        output = MissionSnapshot(mission_id=mission.id, framing_id=session.id, framing_revision=1,
                                 mode="demo", status="failed", sequence=0, steps=[step]).model_dump_json()
    elif surface == "trace":
        writer = TraceWriter(mission.id, tmp_path)
        writer.write(event)
        output = writer.path.read_text()
    elif surface == "replay":
        trace = ReplayTrace.from_mission_snapshot(mission.snapshot(include_events=True))
        trace.dump(tmp_path / "replay.json")
        output = (tmp_path / "replay.json").read_text()
    elif surface == "sse":
        envelope = EventEnvelope.build(mission.id, 1, "trace", {"message": SENTINEL, **nested})
        mission.envelopes.append(envelope)
        with TestClient(app) as client:
            output = client.get(f"{route}/events").text
    else:
        with TestClient(app) as client:
            if surface == "live":
                response = client.get("/api/live/parent-probe-session")
            elif surface == "snapshot_api":
                response = client.get(route)
            elif surface == "journey":
                response = client.get(f"{route}/journey")
            elif surface in {"html", "ics", "pdf"}:
                if surface == "pdf":
                    def pdf(html, chrome=None):
                        assert SENTINEL not in html
                        assert "[REDACTED]" in html
                        return b"%PDF-test [REDACTED]"
                    monkeypatch.setattr(recap_adapter, "html_to_pdf", pdf)
                response = client.get(f"{route}/recap.{surface}")
            elif surface == "health":
                service.providers.health["h"].detail = SENTINEL
                response = client.get("/api/health")
            elif surface in {"transcription", "transcription_error"}:
                class Transcriber:
                    async def transcribe(self, *args):
                        if surface == "transcription_error":
                            raise RuntimeError(SENTINEL)
                        return SENTINEL
                service.transcriber = Transcriber()
                response = client.post("/api/transcribe", content=b"synthetic audio")
            elif surface == "validation_error":
                response = client.get(f"{route}/recap.html", params={"revision": SENTINEL})
            elif surface == "http_error":
                @app.get("/probe-error")
                async def error():
                    raise HTTPException(409, nested)
                response = client.get("/probe-error")
            elif surface == "framing_error":
                async def broken_create(request):
                    raise FramingError(SENTINEL)
                app.state.framing.create = broken_create
                response = client.post("/api/framings", json={"text": "une course"})
            else:
                response = client.post("/api/framings", json={"text": f"une course à {SENTINEL}"})
            expected = {"framing": 201, "http_error": 409, "framing_error": 409,
                        "validation_error": 422, "transcription_error": 503}.get(surface, 200)
            assert response.status_code == expected, response.text
            output = response.text
    assert SENTINEL not in output, surface
    assert "[REDACTED]" in output, surface
    if surface in {"step", "snapshot", "snapshot_api", "journey", "live"}:
        json.loads(output)
