from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_framing_engine import Search, mission

from runai.contracts.common import DataMode
from runai.framing.api import build_framing_router
from runai.framing.engine import FramingEngine


def test_routes_revision_and_launch_gate():
    calls = []

    async def launch(session):
        calls.append(session.id)
        return mission(session)

    app = FastAPI()
    app.include_router(
        build_framing_router(FramingEngine(Search(1), DataMode.demo), launch)
    )
    with TestClient(app) as client:
        assert client.get("/api/framings/missing").status_code == 404
        assert client.post("/api/framings", json={"text": ""}).status_code == 422
        response = client.post(
            "/api/framings",
            json={
                "text": (
                    "course à Tokyo, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, train"
                ),
                "channel": "voice",
            },
        )
        assert response.status_code == 201
        session = response.json()
        url = f"/api/framings/{session['id']}"
        assert client.get(url).json() == session
        key = {"revision": 1, "idempotency_key": "confirm-key"}
        assert client.post(url + "/confirm", json=key).status_code == 409
        assert calls == []
        assert (
            client.post(
                url + "/replies", json={"revision": 1, "choice_id": "c0"}
            ).status_code
            == 200
        )
        session = client.post(
            url + "/replies", json={"revision": 2, "text": "budget 900 euros"}
        ).json()
        assert session["revision"] == 3
        assert (
            client.post(url + "/confirm", json=key | {"revision": 2}).status_code == 409
        )
        key["revision"] = 3
        response = client.post(url + "/confirm", json=key)
        assert response.status_code == 200
        assert client.post(url + "/confirm", json=key).json() == response.json()
        assert (
            client.post(
                url + "/confirm", json=key | {"idempotency_key": "other-key"}
            ).status_code
            == 409
        )
        assert len(calls) == 1
        other = client.post(
            "/api/framings", json={"text": "une course à Lisbonne"}
        ).json()
        url = f"/api/framings/{other['id']}"
        assert client.post(url + "/cancel").json()["status"] == "cancelled"
        assert client.post(url + "/confirm", json=key).status_code == 409
        assert len(calls) == 1
