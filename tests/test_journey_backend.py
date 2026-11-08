import json
import re
import time
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.candidates import FixtureCandidateSearch
from runai.app.mission_journey import project_journey
from runai.app.server import build_demo_service, create_app
from runai.contracts.common import Automation, DataMode
from runai.contracts.journey import JourneyPlan
from runai.models import StepKind, StepResult
from runai.planning import recap_adapter
from tests.contracts.test_shared_journey import AT, money, scenario
from tests.test_planning_evidence import quote, rules


class ResultRun:
    session_id = "fixture-result"
    live_view_url = None

    def __init__(self, result):
        self.result = result

    async def wait(self):
        return self.result


@pytest.mark.parametrize("complete", [True, False])
def test_projected_budget_warning_uses_final_costs(complete):
    summary, inputs = scenario("berlin_train")
    inputs.hotel = None
    inputs.local_cost = money(20) if complete else None
    structured = inputs.model_dump(mode="json")
    steps = {
        kind: StepResult(kind=kind, status="completed")
        for kind in (StepKind.registration, StepKind.accommodation, StepKind.transport)
    }
    steps[StepKind.registration].data = {"journey": {"race": structured["race"]}}
    steps[StepKind.accommodation].price_eur = 200
    steps[StepKind.transport].data = {"journey": {
        key: structured[key] for key in ("home", "outbound", "return_trip", "local_cost")
    }}
    mission = SimpleNamespace(
        id="budget-warning", framing_summary=summary, limitations=[], steps=steps,
        created_at=AT, journey=None,
        plan=SimpleNamespace(mode=DataMode.demo, steps={
            kind: SimpleNamespace(automation=Automation.automated) for kind in steps
        }),
    )

    plan, _ = project_journey(mission)

    assert plan.budget.complete is complete
    partial_warnings = [warning for warning in plan.warnings
                        if warning.startswith(("Partial budget:", "Budget partiel :"))]
    assert partial_warnings == ([] if complete else [
        "Partial budget: unpriced items excluded from the total."
    ])


@pytest.mark.parametrize("name", ["berlin_train", "tokyo_flight", "nairobi_incomplete"])
def test_confirmed_journey_revisions_and_shared_exports(tmp_path, monkeypatch, name):
    summary, inputs = scenario(name)
    inputs.race.bib_pickup_closes = inputs.race.start_time
    inputs.race.bib_pickup_time = None
    race = summary.race.model_copy(update={"registration_url": "https://in.njuko.com/fixture"})
    structured = inputs.model_dump(mode="json")
    structured["home"]["provenance"] = {"kind": "human"}
    regulation = rules().model_dump(mode="json")
    regulation["timezone"] = inputs.race.start.timezone
    regulation["race_name"] = race.name

    class Agents:
        async def start(self, kind, *args, **kwargs):
            data = {}
            if kind is StepKind.registration:
                data = {"journey": {"race": structured["race"]}, "quote": quote(frais_inclus_dans_prix=True).model_dump(mode="json"),
                        "rules": regulation, "race_sheet": {"query": race.name, "missing_fields": ["registration_deadline"]}}
            elif kind is StepKind.accommodation and structured["hotel"]:
                data = {"journey": {"hotel": structured["hotel"]}}
            if name == "tokyo_flight":
                data = {"answer": data}
            return ResultRun(StepResult(kind=kind, status="stopped_before_commitment", stop_point="payment", data=data))

    service = build_demo_service(delay=0)
    service.agents = Agents()
    service.traces_dir = tmp_path
    app = create_app(service)
    app.state.framing.search = FixtureCandidateSearch([race], DataMode.demo)
    rendered = []

    def pdf(snapshot):
        rendered.append(snapshot)
        return b"%PDF-test"

    monkeypatch.setattr(recap_adapter, "render_pdf", pdf)
    with TestClient(app) as client:
        session = client.post("/api/framings", json={
            "text": (
                f"une course à {race.city}, {race.distance_km} km "
                f"{race.race_date.isoformat()} depuis Paris, "
                "2000 euros, 2 nuits, train"
            )
        }).json()
        assert not service.missions
        assert client.get(f"/api/missions/{session['id']}/journey").status_code == 404
        session = client.post(f"/api/framings/{session['id']}/replies", json={
            "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
        }).json()
        session = client.post(f"/api/framings/{session['id']}/replies", json={
            "revision": session["revision"], "corrections": {"origin": summary.origin_public, "budget": 2000,
                "nights": 2, "transport_mode": summary.transport_mode},
        }).json()
        confirmed = client.post(f"/api/framings/{session['id']}/confirm", json={
            "revision": session["revision"], "idempotency_key": "journey-test-confirm",
        })
        assert confirmed.status_code == 200, confirmed.text
        mid = confirmed.json()["mission_id"]
        route = f"/api/missions/{mid}"
        old = client.get(f"{route}/recap.html?revision=0").text
        for _ in range(200):
            snapshot = client.get(route).json()
            if snapshot["status"] == "awaiting_human":
                break
            time.sleep(.005)
        mission = service.get(mid)
        # These are manually supplied transport choices, not a flight agent launch.
        mission.steps[StepKind.transport].data["journey"] = {key: structured[key] for key in ("home", "outbound", "return_trip")}
        client.portal.call(service._refresh_journey, mission)
        plan = JourneyPlan.model_validate(client.get(f"{route}/journey").json())
        assert plan.revision > 0
        assert plan.budget.known_total >= 30
        assert any(l.code == "missing_registration_deadline" for l in plan.limitations)
        assert all(segment.automation.value != "automated" for segment in plan.segments if segment.mode.value == "flight")
        bib = next(stop for stop in plan.stops if stop.id == "bib")
        assert bib.local_time is None
        assert any("not an appointment" in warning for warning in plan.warnings)
        if name == "nairobi_incomplete":
            assert all(segment.geometry is None for segment in plan.segments if segment.mode.value == "local")
        revision = plan.revision
        client.portal.call(service._refresh_journey, mission)
        assert client.get(f"{route}/journey").json()["revision"] == revision
        snapshot = client.get(route).json()
        assert snapshot["journey_revision"] == revision
        assert snapshot["budget"] == plan.budget.model_dump(mode="json")
        manual = next(q for q in snapshot["questions"] if "medical_certificate" in q["question_id"] or "medical_certificate" in q["text"])
        assert manual["session_id"] is None and manual["reason"].startswith("eligibility:")
        response = client.post(f"{route}/questions/{manual['question_id']}/answer", json={
            "answer": "Oui, santé et consentement autorisés", "revision": manual["revision"], "idempotency_key": "manual-test-answer",
        })
        assert response.status_code == 409
        assert response.json()["detail"]
        current = client.get(route).json()
        assert next(q for q in current["questions"] if q["question_id"] == manual["question_id"])["status"] == "open"
        expected = recap_adapter.recap_from_journey(plan)
        html = client.get(f"{route}/recap.html?revision={revision}")
        ics = client.get(f"{route}/recap.ics?revision={revision}")
        pdf_result = client.get(f"{route}/recap.pdf?revision={revision}")
        assert html.text == recap_adapter.render_html(expected)
        assert ics.content == recap_adapter.render_ics(expected)
        assert pdf_result.content == b"%PDF-test" and rendered == [expected]
        assert html.headers["x-runai-journey-revision"] == str(revision)
        assert "BEGIN:VCALENDAR" in ics.text and "revision" in html.text
        assert client.get(f"{route}/recap.html?revision=0").text == old
        assert client.get(f"{route}/recap.ics?revision=999").status_code == 404
        assert client.get(f"{route}/recap.txt").status_code == 404
        assert "journey_revised" in client.get(f"{route}/events").text


def test_served_shell_resources_and_fixture_mounts_have_no_missing_local_urls(tmp_path):
    class Resources(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "script" and attrs.get("src"):
                self.urls.append(attrs["src"])
            if tag == "link" and attrs.get("rel") == "stylesheet":
                self.urls.append(attrs["href"])

    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        page = client.get("/?mock=1")
        parser = Resources()
        parser.feed(page.text)
        local = [url for url in parser.urls if url.startswith("/")]
        scripts = json.loads(re.search(r"RUNAI_JOURNEY_SCRIPTS = (\[[\s\S]*?\]);", page.text)[1])
        assert [url.rsplit("/", 1)[1] for url in scripts[:5]] == ["journey-contract.js", "route.js", "journey-data.js", "journey-player.js", "journey-fallback.js"]
        assert page.text.index("RUNAI_JOURNEY_SCRIPTS") < page.text.index('src="/static/app.js"')
        assert "/static/voice/voice-input.js" in local
        for url in local + scripts:
            response = client.get(url)
            assert response.status_code == 200, url
        mock = client.get("/static/mock-api.js").text
        for fixture in set(re.findall(r'"([a-z_]+\.json)"', mock)):
            assert client.get(f"/static/contract-fixtures/{fixture}").status_code == 200
        assert client.get("/api/missions/unknown/journey").status_code == 404
        assert client.get("/api/missions/unknown/recap.html").status_code == 404


def test_invalid_step_geometry_and_export_error_are_explicit_and_redacted(tmp_path, monkeypatch):
    from tests.test_v2_backend import confirm, prepare

    secret = "test-stage3-secret-no-leak"
    monkeypatch.setenv("HAI_API_KEY", secret)

    class Agents:
        async def start(self, kind, *args, **kwargs):
            data = {"journey": {"race": {"start": {"label": secret, "coords": {"lat": 900, "lon": 0}}}}} if kind is StepKind.registration else {}
            return ResultRun(StepResult(kind=kind, status="stopped_before_commitment", stop_point="payment", data=data))

    service = build_demo_service(delay=0)
    service.agents = Agents()
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Tokyo")).json()["mission_id"]
        route = f"/api/missions/{mid}"
        for _ in range(200):
            snapshot = client.get(route).json()
            if snapshot["status"] == "awaiting_human":
                break
            time.sleep(.005)
        assert any(l["code"] == "journey_data_invalid" for l in snapshot["limitations"])
        assert client.get(f"{route}/journey").json()["revision"] == 0

        def broken_pdf(snapshot):
            raise RuntimeError(f"PDF indisponible : {secret}")

        monkeypatch.setattr(recap_adapter, "render_pdf", broken_pdf)
        response = client.get(f"{route}/recap.pdf")
        assert response.status_code == 503 and "[REDACTED]" in response.text
        assert secret not in response.text + json.dumps(snapshot) + client.get(f"{route}/events").text
