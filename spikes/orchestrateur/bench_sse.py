"""Mesure locale : latence SSE (publication -> reception client), latence des commandes, attente en file.

lancer : ../../.venv/bin/python bench_sse.py [--trips 5] [--speed 1]
Aucune session H : adaptateur mock, serveur uvicorn reel sur 127.0.0.1.
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time

import httpx
from runai_orch.adapters.mock import MockHAdapter
from tests.live_server import LiveServer

BODY = {"race_name": "10 km du Maine Libre", "race_date": "2027-03-07", "city": "Le Mans", "distance_km": 10}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


def reader(url, out, stop_states, on_event=None, stop_types=()):
    with httpx.Client(timeout=60) as c, c.stream("GET", url) as r:
        out.append(({"type": "_connected", "ts": time.time()}, time.time()))
        data = None
        for line in r.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
            elif line == "" and data:
                ev, data = json.loads(data), None
                if not ev:
                    return
                out.append((ev, time.time()))
                if on_event:
                    on_event(ev)
                if (ev["state"] in stop_states and ev["type"] == "state") or ev["type"] in stop_types:
                    return


def one_trip(c, base, lat, cmd):
    t0 = time.perf_counter()
    trip = c.post("/missions", json=BODY).json()
    cmd["post_ms"].append((time.perf_counter() - t0) * 1000)
    got = {m["id"]: [] for m in trip["missions"]}
    ins = trip["missions"][0]["id"]
    sent = {}

    def on_ins(ev):
        if ev["type"] == "state" and ev["state"] == "waiting_human" and "msg" not in sent:
            sent["msg"] = time.time()
            threading.Thread(target=lambda: c.post(f"/missions/{ins}/message", json={"text": "ok je coche"})).start()
        if "msg" in sent and ev["type"] == "state" and ev["state"] == "running" and "ack" not in sent:
            sent["ack"] = time.time()

    ths = [threading.Thread(target=reader, args=(f"{base}/missions/{mid}/events", got[mid], {"ready_to_pay", "failed"},
                                                 on_ins if mid == ins else None)) for mid in got]
    for t in ths:
        t.start()
    for t in ths:
        t.join(60)
    for evs in got.values():
        connected = evs[0][0]["ts"]
        # seuls les evenements publies apres la connexion mesurent le direct (les autres sont rejoues)
        lat.extend((recv - ev["ts"]) * 1000 for ev, recv in evs[1:] if ev["ts"] >= connected)
        cmd["replayed_events"].append(sum(1 for ev, _ in evs[1:] if ev["ts"] < connected))
    cmd["message_to_running_ms"].append((sent["ack"] - sent["msg"]) * 1000)
    cmd["e2e_s"].append(max(evs[-1][1] for evs in got.values()) - min(evs[1][0]["ts"] for evs in got.values()))
    return trip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", type=int, default=5)
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    lat, cmd = [], {"post_ms": [], "message_to_running_ms": [], "e2e_s": [], "pause_rtt_ms": [], "queue_start_ms": [],
                  "replayed_events": []}
    with LiveServer(MockHAdapter(speed=a.speed), poll_s=0.05) as srv, httpx.Client(base_url=srv.url, timeout=30) as c:
        for _ in range(a.trips):
            trip = one_trip(c, srv.url, lat, cmd)
            # file d'attente : les 3 slots sont tenus (ready_to_pay = session idle), une 4e mission attend
            q = c.post("/missions", json={**BODY, "kinds": ["hotel"]}).json()["missions"][0]
            time.sleep(0.2)
            assert c.get(f"/missions/{q['id']}").json()["state"] == "queued"
            started = []
            th = threading.Thread(target=reader, args=(f"{srv.url}/missions/{q['id']}/events", started, set()),
                                  kwargs={"stop_types": ("live_view",)})
            th.start()
            time.sleep(0.1)
            t0 = time.time()
            c.post(f"/missions/{trip['missions'][1]['id']}/cancel")
            th.join(30)
            # slot rendu -> session suivante creee (evenement live_view emis juste apres adapter.start)
            run_ev = next(recv for ev, recv in started if ev["type"] == "live_view")
            cmd["queue_start_ms"].append((run_ev - t0) * 1000)
            time.sleep(0.3)  # le mock passe en running apres 0,2 s
            # pause aller-retour HTTP
            if c.get(f"/missions/{q['id']}").json()["state"] == "running":
                t1 = time.perf_counter()
                if c.post(f"/missions/{q['id']}/pause").status_code == 200:
                    cmd["pause_rtt_ms"].append((time.perf_counter() - t1) * 1000)
            for m in [*trip["missions"], q]:
                c.post(f"/missions/{m['id']}/cancel")
    res = {"events": len(lat),
           "sse_latency_ms": {"p50": round(statistics.median(lat), 2), "p95": round(pct(lat, 95), 2),
                              "max": round(max(lat), 2)},
           **{k: {"n": len(v), "median": round(statistics.median(v), 2), "max": round(max(v), 2)}
              for k, v in cmd.items() if v}}
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
