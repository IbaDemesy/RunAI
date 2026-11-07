"""Google Calendar : free/busy en lecture et ajout du week-end (non testé : il faut un client OAuth).

Scopes minimaux : https://www.googleapis.com/auth/calendar.freebusy (lecture des créneaux occupés) et
https://www.googleapis.com/auth/calendar.app.created (crée un agenda « RunAI » dédié et y écrit,
sans toucher aux autres agendas). En mode « Testing », le refresh token expire au bout de 7 jours.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

import httpx

API = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar.freebusy",
          "https://www.googleapis.com/auth/calendar.app.created"]


def url_autorisation(client_id: str, redirect_uri: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"})


def occupations(token: str, debut: datetime, fin: datetime, calendriers: tuple[str, ...] = ("primary",)) -> list[dict]:
    r = httpx.post(f"{API}/freeBusy", headers={"Authorization": f"Bearer {token}"}, timeout=30, json={
        "timeMin": debut.isoformat(), "timeMax": fin.isoformat(), "items": [{"id": c} for c in calendriers]})
    r.raise_for_status()
    return [b for c in r.json()["calendars"].values() for b in c.get("busy", [])]


def ajouter_week_end(token: str, evenements: list[dict], nom: str = "RunAI") -> list[str]:
    h = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30, headers=h) as c:
        cal = c.post(f"{API}/calendars", json={"summary": nom})
        cal.raise_for_status()
        ids = []
        for ev in evenements:
            r = c.post(f"{API}/calendars/{cal.json()['id']}/events", json={
                "summary": ev["titre"], "location": ev.get("lieu", ""), "description": ev.get("description", ""),
                "start": {"dateTime": ev["debut"].isoformat()}, "end": {"dateTime": ev["fin"].isoformat()}})
            r.raise_for_status()
            ids.append(r.json()["id"])
    return ids
