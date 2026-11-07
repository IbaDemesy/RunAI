"""Petit client REST H Agents API (EU) pour le spike boucle_devin."""

import os
import time

import httpx

BASE = "https://agp.eu.hcompany.ai/api/v2"
TERMINAL = {"completed", "failed", "timed_out", "interrupted", "cancelled"}


def client() -> httpx.Client:
    key = os.environ.get("HAI_API_KEY")
    if not key:
        raise SystemExit("HAI_API_KEY manquante")
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {key}"}, timeout=60)


def wait_for_slot(c: httpx.Client, max_wait_s: int = 600, every_s: int = 60) -> dict:
    t0 = time.time()
    while True:
        q = c.get("/sessions/quota").json()
        if q.get("available", 0) > 0:
            q["waited_s"] = round(time.time() - t0, 1)
            return q
        if time.time() - t0 > max_wait_s:
            raise SystemExit(f"Aucun slot H libre après {max_wait_s} s: {q}")
        print(f"quota plein {q}, nouvel essai dans {every_s} s")
        time.sleep(every_s)


def put_skill(c: httpx.Client, name: str, description: str, body: str, message: str) -> int:
    payload = {"name": name, "description": description, "body": body}
    r = c.put(f"/skills/{name}", json=payload, params={"message": message})
    if r.status_code == 404:
        r = c.post("/skills", json=payload, params={"message": message})
    r.raise_for_status()
    return int(r.headers["ETag"].strip('"'))


def skill_revisions(c: httpx.Client, name: str) -> list[dict]:
    r = c.get(f"/skills/{name}/revisions")
    r.raise_for_status()
    return r.json()["items"]


def put_agent(c: httpx.Client, spec: dict, message: str) -> int:
    r = c.put(f"/agents/{spec['name']}", json=spec, params={"message": message})
    if r.status_code == 404:
        r = c.post("/agents", json=spec, params={"message": message})
    r.raise_for_status()
    return int(r.headers["ETag"].strip('"'))


def run_session(c: httpx.Client, agent: str, task: str, max_steps: int, max_time_s: int) -> dict:
    """Crée une session, attend un statut terminal, et l'annule toujours à la fin."""
    sid = None
    t0 = time.time()
    try:
        r = c.post(
            "/sessions",
            json={"agent": agent, "messages": task, "max_steps": max_steps, "max_time_s": max_time_s},
        )
        r.raise_for_status()
        sid = r.json()["id"]
        print("session H", sid)
        status = None
        while time.time() - t0 < max_time_s + 300:
            status = c.get(f"/sessions/{sid}/status").json().get("status")
            if status in TERMINAL:
                break
            time.sleep(5)
        session = c.get(f"/sessions/{sid}").json()
        session["_duration_s"] = round(time.time() - t0, 1)
        return session
    finally:
        if sid:
            d = c.delete(f"/sessions/{sid}")
            print("cancel", sid, d.status_code)


def all_events(c: httpx.Client, sid: str) -> list[dict]:
    events, page = [], 1
    while True:
        r = c.get(f"/sessions/{sid}/events", params={"page": page, "size": 200, "sort": "timestamp"})
        r.raise_for_status()
        data = r.json()
        events += data["items"]
        if len(events) >= data["total"] or not data["items"]:
            return events
        page += 1
