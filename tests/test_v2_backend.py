import json
import time

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import DEMO_RACES
from runai.app.server import build_demo_service, build_service, create_app
from runai.contracts.common import DataMode, ProvenanceKind
from runai.search.candidates import CandidateSearchError


def prepare(client, city, *, channel="text", nights=2):
    distance = "42.195 km" if city == "Milan" else "10 km"
    period = "avril 2027" if city == "Milan" else "juin 2028"
    mode = "train" if city == "Milan" else "avion"
    text = (
        f"une course à {city}, {distance} en {period}, depuis Lyon, "
        f"900 euros, {nights} nuits, {mode}"
    )
    response = client.post("/api/framings", json={"text": text, "channel": channel})
    assert response.status_code == 201
    session = response.json()
    assert session["status"] == "choosing_candidate"
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
    }).json()
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "corrections": {
            "origin": "Lyon", "budget": 900, "nights": nights,
            "transport_mode": "train" if city == "Milan" else "flight",
        }, "channel": channel,
    }).json()
    assert session["status"] == "ready_to_confirm", session
    return session


def confirm(client, session):
    return client.post(f"/api/framings/{session['id']}/confirm", json={
        "revision": session["revision"], "idempotency_key": "confirm-v2-test",
    })


def finish(client, mid):
    for _ in range(200):
        mission = client.get(f"/api/missions/{mid}").json()
        for question in mission["questions"]:
            if question["status"] == "open":
                response = client.post(f"/api/missions/{mid}/questions/{question['question_id']}/answer", json={
                    "revision": question["revision"], "idempotency_key": f"answer-{question['question_id']}",
                    "answer": question["choices"][0],
                })
                assert response.status_code == 200
        if mission["status"] in {"awaiting_human", "failed", "completed", "cancelled"}:
            return mission
        time.sleep(.005)
    pytest.fail("Mission non terminée")


@pytest.mark.parametrize(("city", "channel"), [("Milan", "text"), ("Tokyo", "voice")])
def test_confirmed_demo_mission_is_idempotent_and_sse_resumes(tmp_path, city, channel):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        assert client.post("/api/missions", json={"query": "une course"}).status_code == 410
        session = prepare(client, city, channel=channel)
        assert not service.missions
        first = confirm(client, session)
        assert first.status_code == 200
        mission = first.json()
        assert mission["schema_version"] == "mission.v2"
        mid = mission["mission_id"]
        assert confirm(client, session).json()["mission_id"] == mid
        assert len(service.missions) == 1
        final = finish(client, mid)
        assert final["race"]["city"] == city
        assert final["mode"] == "demo" and final["status"] == "awaiting_human"
        runs = service.agents.agents.runs
        assert len(runs) == (3 if city == "Milan" else 2)
        assert all(run.brief.city == city and run.brief.origin == "Lyon" for run in runs)
        assert all(step["data"].get("provenance", {}).get("mode") == "demo"
                   for step in final["steps"] if step["data"]["automation"] == "automated")
        if city == "Tokyo":
            transport = next(s for s in final["steps"] if s["kind"] == "transport")
            assert transport["data"]["automation"] == "manual"
            assert any(l["code"] == "transport_not_covered" for l in final["limitations"])
        stream = client.get(f"/api/missions/{mid}/events")
        envelopes = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        assert all(e["schema_version"] == "events.v1" for e in envelopes)
        assert [e["sequence"] for e in envelopes] == list(range(1, len(envelopes) + 1))
        cursor = envelopes[2]["event_id"]
        resumed = client.get(f"/api/missions/{mid}/events", headers={"Last-Event-ID": cursor})
        ids = [line[4:] for line in resumed.text.splitlines() if line.startswith("id: ")]
        assert ids == [e["event_id"] for e in envelopes[3:]]
        assert client.get(f"/api/missions/{mid}/events", headers={"Last-Event-ID": "wrong:2"}).status_code == 409


@pytest.mark.parametrize("request_text", [
    "A race in Nairobi, 10 km on 2028-10-01, from Mombasa, 900 euros, 2 nights, bus",
    "A half marathon in China on 2028-10-01, from Mombasa, 900 euros, 2 nights, bus",
])
def test_unmatched_demo_request_requires_explicit_recorded_candidate_choice(tmp_path, request_text):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        session = client.post("/api/framings", json={
            "text": request_text,
        }).json()
        assert session["status"] == "choosing_candidate"
        assert len(session["candidates"]) == len(DEMO_RACES)
        assert {(c["name"], c["city"], c["race_date"], tuple(c["distances_km"]))
                for c in session["candidates"]} == {
            (race.name, race.city, race.race_date.isoformat(), (race.distance_km,))
            for race in DEMO_RACES.values()
        }
        assert all(any(limit["code"] == "close_match" for limit in candidate["limitations"])
                   for candidate in session["candidates"])
        assert any(limit["code"] == "demo_closest" for limit in session["limitations"])
        assert session["selected_candidate_id"] is None
        assert confirm(client, session).status_code == 409
        assert not service.missions and not service.agents.agents.runs
        session = client.post(f"/api/framings/{session['id']}/replies", json={
            "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
        }).json()
        assert session["status"] == "ready_to_confirm"
        assert session["summary"]["race"]["name"] == DEMO_RACES["milan"].name
        assert not service.missions and not service.agents.agents.runs


def test_live_missing_keys_and_linkup_failure_are_honest(monkeypatch, tmp_path):
    for name in ("HAI_API_KEY", "HAI_API_KEY_2", "HAI_API_KEY_3", "LINKUP_API_KEY", "GLADIA_API_KEY", "RUNAI_DEMO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNAI_MODE", "live")
    service = build_service()
    service.traces_dir = tmp_path
    app = create_app(service)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "live" and not health["simulated"]
        assert set(health["providers"].values()) == {"missing_key"}
        session = client.post("/api/framings", json={
            "text": (
                "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                "900 euros, 2 nuits, train"
            )
        }).json()
        assert session["candidates"] == []
        assert any(l["code"] == "candidate_provider_error" for l in session["limitations"])
        assert client.post("/api/transcribe", content=b"audio").status_code == 503
        assert not service.missions

        secret = "test-linkup-key-which-must-not-leak"
        monkeypatch.setenv("LINKUP_API_KEY", secret)

        class BrokenSearch:
            async def find_candidates(self, slots, request_text: str | None = None):
                raise CandidateSearchError(f"Linkup indisponible : {secret}")

        app.state.framing.search = BrokenSearch()
        broken = client.post("/api/framings", json={
            "text": (
                "une course à Chicago, 10 km en juin 2028, depuis Lyon, "
                "900 euros, 2 nuits, train"
            )
        }).json()
        assert any(l["message"] == "Linkup indisponible : [REDACTED]" for l in broken["limitations"])
        assert secret not in json.dumps(broken)


def test_cancel_and_stale_or_expired_question_cannot_restart(tmp_path):
    service = build_demo_service(delay=.03)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        cancelled = prepare(client, "Tokyo")
        assert client.post(f"/api/framings/{cancelled['id']}/cancel").status_code == 200
        assert confirm(client, cancelled).status_code == 409
        assert not service.missions
        session = prepare(client, "Tokyo")
        mid = confirm(client, session).json()["mission_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/missions/{mid}").json()
            if snapshot["questions"]:
                break
            time.sleep(.005)
        q = snapshot["questions"][0]
        url = f"/api/missions/{mid}/questions/{q['question_id']}/answer"
        body = {"answer": "Découverte", "revision": q["revision"] - 1, "idempotency_key": "stale-answer"}
        assert client.post(url, json=body).status_code == 409
        response = client.post(f"/api/missions/{mid}/cancel")
        assert response.json()["status"] == "cancelled"
        count = len(service.agents.agents.runs)
        assert client.post(url, json=body | {"revision": q["revision"]}).status_code == 409
        assert client.post(f"/api/missions/{mid}/cancel").json()["status"] == "cancelled"
        assert len(service.agents.agents.runs) == count
        assert all(s["status"] != "open" for s in client.get(f"/api/missions/{mid}").json()["questions"])


def test_live_queued_controls_and_cancellation_keep_cancelled_status(tmp_path):
    import asyncio

    from runai.app.real import RealBrowserAgents

    class WaitingRunner:
        async def start(self, *args, **kwargs):
            await asyncio.Event().wait()

        async def aclose(self):
            pass

    service = build_demo_service(delay=0)
    service.agents = RealBrowserAgents(runner=WaitingRunner())
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        session = prepare(client, "Tokyo")
        mid = confirm(client, session).json()["mission_id"]
        for _ in range(200):
            if len(service._runs) == 2:
                break
            time.sleep(.005)
        assert len(service.agents.lifecycle.active(mid)) == 2
        route = f"/api/missions/{mid}"
        assert client.post(f"{route}/steps/registration/message", json={"text": "Attendez"}).status_code == 409
        assert client.post(f"{route}/pause").status_code == 200
        assert client.post(f"{route}/resume").status_code == 200
        cancelled = client.post(f"{route}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert client.get(route).json()["status"] == "cancelled"
        assert not service.agents.lifecycle.active(mid)
        assert all(job._task.done() for job in service.agents.lifecycle.jobs.values())
        assert '"code":"h_cancelled"' in client.get(f"{route}/events").text


def test_expired_question_endpoint_rejects_answer(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    service.question_timeout_s = .01
    with TestClient(create_app(service)) as client:
        session = prepare(client, "Tokyo")
        mid = confirm(client, session).json()["mission_id"]
        time.sleep(.04)
        snapshot = client.get(f"/api/missions/{mid}").json()
        q = snapshot["questions"][0]
        assert q["status"] == "expired"
        assert client.post(f"/api/missions/{mid}/questions/{q['question_id']}/answer", json={
            "answer": "Découverte", "revision": q["revision"], "idempotency_key": "expired-answer",
        }).status_code == 409


def test_replay_candidates_only_match_trace_and_keep_replay_provenance(tmp_path, monkeypatch):
    from runai.app.fakes import DEMO_RACES
    from runai.app.replay import ReplayTrace

    trace = tmp_path / "trace.json"
    ReplayTrace(label="Tokyo", race=DEMO_RACES["tokyo"]).dump(trace)
    monkeypatch.setenv("RUNAI_REPLAY_TRACE", str(trace))
    service = build_service(mode=DataMode.replay, delay=0)
    with TestClient(create_app(service)) as client:
        session = client.post("/api/framings", json={
            "text": (
                "une course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                "900 euros, 2 nuits, train"
            )
        }).json()
        assert session["candidates"][0]["provenance"]["kind"] == "replay"
        other = client.post("/api/framings", json={
            "text": (
                "une course à Milan, 42.195 km en avril 2027, depuis Lyon, "
                "900 euros, 2 nuits, train"
            )
        }).json()
        assert not other["candidates"]


def test_mission_secrets_are_redacted_on_snapshot_and_sse(tmp_path, monkeypatch):
    secret = "test-secret-v2-error"
    monkeypatch.setenv("LINKUP_API_KEY", secret)
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path

    class BrokenAgents:
        async def start(self, *args, **kwargs):
            raise RuntimeError(secret)

    service.agents = BrokenAgents()
    with TestClient(create_app(service)) as client:
        session = prepare(client, "Tokyo")
        mid = confirm(client, session).json()["mission_id"]
        assert finish(client, mid)["status"] == "failed"
        assert secret not in client.get(f"/api/missions/{mid}").text
        stream = client.get(f"/api/missions/{mid}/events").text
        assert secret not in stream and "[REDACTED]" in stream


@pytest.mark.parametrize(("outcome", "code"), [
    ("normal", None), ("no_stop", None), ("anti_bot", "h_anti_bot"),
    ("timeout", "h_timeout"), ("missing", "h_key_missing"), ("quota", "h_quota_saturated"),
])
def test_live_lifecycle_preserves_guards_errors_and_closes_idle(tmp_path, outcome, code):
    from runai.app.candidates import FixtureCandidateSearch
    from runai.app.fakes import DEMO_RACES
    from runai.app.real import RealBrowserAgents
    from runai.h.lifecycle import HKeyMissing
    from runai.h.runner import HQuotaTimeout
    from runai.models import StepKind, StepResult, StepStatus

    class Run:
        live_view_url = None
        agent_view_url = None

        def __init__(self, kind, tools):
            self.id = f"stub-{kind.value}"
            self.kind = kind
            self.tools = tools
            self.status = "timed_out" if outcome == "timeout" else "idle"
            self.closed = False

        async def wait(self, **kwargs):
            if outcome == "normal" and self.kind is StepKind.registration:
                await self.tools[0].fn(question="Quel sas souhaitez-vous ?", options=["Découverte"])
            if outcome == "anti_bot":
                return StepResult(kind=self.kind, status="failed", error="captcha/anti-bot")
            if outcome == "timeout":
                return StepResult(kind=self.kind, status="failed", error="timeout")
            return StepResult(
                kind=self.kind,
                status="completed" if outcome == "no_stop" else "stopped_before_commitment",
                stop_point=None if outcome == "no_stop" else "payment",
                summary="PRIX_TOTAL_3_NUITS: 150 EUR" if self.kind is StepKind.accommodation else "Arrêt avant paiement",
            )

        async def close(self):
            self.closed = True

    class Runner:
        def __init__(self):
            self.runs = []
            self.params = []

        async def start(self, kind, task, **kwargs):
            if outcome == "missing":
                raise HKeyMissing("Clé H manquante")
            if outcome == "quota":
                raise HQuotaTimeout("Quota saturé")
            self.params.append(kwargs)
            run = Run(kind, kwargs["tools"])
            self.runs.append(run)
            return run

        async def aclose(self):
            pass

    class Search(FixtureCandidateSearch):
        async def search(self, slots, request_text: str | None = None):
            result = await super().search(slots)
            for candidate in result.candidates:
                candidate.provenance.kind = ProvenanceKind.linkup
            return result

    service = build_demo_service(delay=0)
    runner = Runner()
    service.agents = RealBrowserAgents(runner=runner)
    service.providers.mode = DataMode.live
    service.simulated = False
    service.traces_dir = tmp_path
    app = create_app(service)
    app.state.framing.search = Search([DEMO_RACES["tokyo"]], DataMode.demo)
    with TestClient(app) as client:
        session = prepare(client, "Tokyo", nights=3)
        mid = confirm(client, session).json()["mission_id"]
        mission = finish(client, mid)
        assert mission["mode"] == "live"
        if code:
            assert code in {l["code"] for l in mission["limitations"]}
            assert f'"code":"{code}"' in client.get(f"/api/missions/{mid}/events").text
        if outcome == "normal":
            hotel = next(s for s in mission["steps"] if s["kind"] == "accommodation")
            assert hotel["price_eur"] == 150
            assert hotel["data"]["budget_max_total_eur"] == 900
            assert hotel["data"]["provenance"]["mode"] == "live"
            assert mission["questions"][0]["session_id"] == "stub-registration"
            assert runner.params[0]["start_url"] == str(DEMO_RACES["tokyo"].registration_url)
            assert all(s["h_session_id"].startswith("stub-") for s in mission["steps"] if s["data"]["automation"] == "automated")
        if outcome == "no_stop":
            assert all(s["status"] == StepStatus.failed.value for s in mission["steps"] if s["data"]["automation"] == "automated")
        assert all(run.closed for run in runner.runs)
        assert not service.agents.lifecycle.active(mid)
