"""Recupere la derniere capture d'une session H deja terminee (aucun nouveau run H).

Usage: python fetch_h_capture.py <session_id> <sortie.png>
Imprime en JSON: url de la page, titre, horodatage, nombre d'etapes, duree.
"""

import json
import os
import sys
from datetime import datetime

import httpx

BASE = "https://agp.eu.hcompany.ai/api/v2"


def _client() -> httpx.Client:
    key = os.environ.get("HAI_API_KEY")
    if not key:
        sys.exit("HAI_API_KEY manquante")
    return httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=60, follow_redirects=True)


def last_observation(c: httpx.Client, session_id: str) -> dict:
    r = c.get(f"{BASE}/sessions/{session_id}/events", params={"size": 200, "sort": "-timestamp", "type": "AgentEvent"})
    r.raise_for_status()
    for ev in r.json()["items"]:
        data = ev["data"]
        if data.get("kind") == "observation_event" and (data.get("image") or {}).get("source"):
            return {"timestamp": ev["timestamp"], **data}
    raise RuntimeError("aucune observation avec capture")


def main(session_id: str, out_path: str) -> None:
    with _client() as c:
        session = c.get(f"{BASE}/sessions/{session_id}").raise_for_status().json()
        obs = last_observation(c, session_id)
        img = c.get(obs["image"]["source"]).raise_for_status()
        with open(out_path, "wb") as f:
            f.write(img.content)
    started = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(session["finished_at"].replace("Z", "+00:00"))
    meta = obs.get("metadata") or {}
    print(json.dumps({
        "session_id": session_id,
        "status": session["status"]["status"],
        "steps": session["status"]["steps"],
        "duration_s": round((finished - started).total_seconds()),
        "capture_at": obs["timestamp"],
        "page_url": meta.get("url"),
        "page_title": meta.get("title"),
        "bytes": len(img.content),
        "content_type": img.headers.get("content-type"),
        "agent_view_url": session.get("agent_view_url"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
