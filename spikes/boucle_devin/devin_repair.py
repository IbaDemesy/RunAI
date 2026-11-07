"""Étape de réparation : session Devin via l'API v3 si DEVIN_API_KEY existe, sinon simulation."""

import os
import time
from pathlib import Path

import httpx

DEVIN_API = "https://api.devin.ai/v3"
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_body": {"type": "string", "description": "Nouveau corps Markdown complet du skill"},
        "change_message": {"type": "string", "maxLength": 500},
        "pr_url": {"type": ["string", "null"]},
    },
    "required": ["skill_body", "change_message"],
}


def repair(prompt: str, simulated_fix: Path, timeout_s: int = 1800) -> dict:
    key, org = os.environ.get("DEVIN_API_KEY"), os.environ.get("DEVIN_ORG_ID")
    if not (key and org):
        body = simulated_fix.read_text()
        msg = simulated_fix.with_suffix(".message.txt").read_text().strip()
        return {"mode": "simule", "skill_body": body, "change_message": msg,
                "note": "DEVIN_API_KEY/DEVIN_ORG_ID absents : correctif écrit à la main à partir du prompt"}
    h = {"Authorization": f"Bearer {key}"}
    t0 = time.time()
    r = httpx.post(
        f"{DEVIN_API}/organizations/{org}/sessions",
        headers=h,
        timeout=60,
        json={
            "prompt": prompt,
            "title": "RunAI : réparer le skill H runai-books-runbook",
            "repos": ["IbaDemesy/RunAI"],
            "tags": ["runai", "boucle-devin"],
            "max_acu_limit": int(os.environ.get("DEVIN_MAX_ACU", "3")),
            "structured_output_schema": OUTPUT_SCHEMA,
        },
    )
    r.raise_for_status()
    sid = r.json()["session_id"]
    while time.time() - t0 < timeout_s:
        s = httpx.get(f"{DEVIN_API}/organizations/{org}/sessions/{sid}", headers=h, timeout=60).json()
        out = s.get("structured_output")
        if out and out.get("skill_body"):
            return {"mode": "devin_api", "devin_session_id": sid, "devin_url": s.get("url"),
                    "duration_s": round(time.time() - t0), **out}
        if s.get("status") in ("exit", "error", "suspended"):
            raise RuntimeError(f"session Devin {sid} terminée sans correctif : {s.get('status')}")
        time.sleep(20)
    raise TimeoutError(f"session Devin {sid} sans correctif après {timeout_s} s")
