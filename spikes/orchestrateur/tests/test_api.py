import json
import time

import httpx
from runai_orch.adapters.mock import MockHAdapter

from tests.live_server import LiveServer

BODY = {"race_name": "10 km du Maine Libre", "race_date": "2027-03-07", "city": "Le Mans", "distance_km": 10}


def sse(client, url, until, headers=None, timeout=10.0):
    """Lit le flux SSE jusqu'a ce que until(event) soit vrai. Renvoie [(event, recu_a)]."""
    out = []
    with client.stream("GET", url, headers=headers, timeout=timeout) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        data = None
        for line in r.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
            elif line == "" and data:
                ev = json.loads(data)
                data = None
                if not ev:
                    break
                out.append((ev, time.time()))
                if until(ev):
                    break
    return out


def test_post_missions_sse_and_commands():
    with LiveServer(MockHAdapter(speed=20)) as srv, httpx.Client(base_url=srv.url) as c:
        r = c.post("/missions", json=BODY)
        assert r.status_code == 201
        trip = r.json()
        kinds = [m["kind"] for m in trip["missions"]]
        assert kinds == ["inscription", "hotel", "transport"]
        assert all(m["state"] == "queued" for m in trip["missions"])
        ins = trip["missions"][0]["id"]

        evs = sse(c, f"/missions/{ins}/events", lambda e: e["state"] == "waiting_human")
        types = {e["type"] for e, _ in evs}
        assert {"state", "live_view", "step", "screenshot"} <= types
        live = next(e for e, _ in evs if e["type"] == "live_view" and e["data"].get("url"))
        assert live["data"]["url"].startswith("https://platform.eu.hcompany.ai/agent-view/")

        assert c.post(f"/missions/{ins}/resume").status_code == 409  # pas en pause
        r = c.post(f"/missions/{ins}/message", json={"text": "C'est bon, je coche"})
        assert r.status_code == 200 and r.json()["state"] == "running"

        last = evs[-1][0]["seq"]
        evs2 = sse(c, f"/missions/{ins}/events", lambda e: e["state"] == "ready_to_pay",
                   headers={"Last-Event-ID": str(last)})
        assert evs2[0][0]["seq"] == last + 1  # reprise sans doublon
        answer = next(e for e, _ in evs2 if e["type"] == "answer")
        assert answer["data"]["verdict"] == "ready_to_pay"

        m = c.get(f"/missions/{ins}").json()
        assert m["state"] == "ready_to_pay" and m["answer"]["payment_submitted"] is False
        assert c.get(f"/trips/{trip['trip_id']}").json()["trip_id"] == trip["trip_id"]
        slots = c.get("/slots").json()
        assert slots["local_limit"] == 3

        r = c.post(f"/missions/{ins}/cancel")
        assert r.json()["state"] == "cancelled"
        tail = sse(c, f"/missions/{ins}/events?from_seq={m and 0}", lambda e: False)
        assert tail[-1][0]["state"] == "cancelled"  # le flux se ferme en etat terminal

        assert c.get("/missions/nope").status_code == 404
        assert c.post("/missions", json={"city": "x"}).status_code == 422
    assert all(m.terminal for m in srv.orch.missions.values())  # shutdown annule tout


def test_pause_from_api_is_seen_on_sse():
    from runai_orch.adapters.base import AdapterEvent as E
    slow = [(0.0, E("status", {"h_status": "running"}))] + [(0.1, E("step", {"thought": f"s{i}"})) for i in range(100)]
    with LiveServer(MockHAdapter(speed=1, scripts={"hotel": slow})) as srv, httpx.Client(base_url=srv.url) as c:
        mid = c.post("/missions", json={**BODY, "kinds": ["hotel"]}).json()["missions"][0]["id"]
        sse(c, f"/missions/{mid}/events", lambda e: e["state"] == "running")
        r = c.post(f"/missions/{mid}/pause")
        assert r.status_code == 200 and r.json()["waiting_reason"] == "paused_by_user"
        assert c.post(f"/missions/{mid}/pause").status_code == 409
        assert c.post(f"/missions/{mid}/resume").json()["state"] == "running"
