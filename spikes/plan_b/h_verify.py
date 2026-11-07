"""1 run H : vérifie dans un vrai navigateur la liste d'attente officielle d'une course complète.

Ne remplit et ne soumet rien. Vérifie le quota avant, annule toujours la session à la fin.
Usage : python h_verify.py --out results/h_lisbon_waitlist.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from hai_agents import Client
from pydantic import BaseModel

QUOTA_URL = "https://agp.eu.hcompany.ai/api/v2/sessions/quota"
URL = "https://meia-maratona.inscricoes.maratonaportugal.com/"
RACE = "EDP Meia Maratona de Lisboa"
TASK = f"""Open {URL}. In the race selector ("Prova"), select "{RACE}" (the 21 km half marathon).
Observe what the page shows after the selection: is it a normal registration form, a sold-out message ("esgotada"),
or a waiting-list form ("Lista de Espera")? Read the exact title/heading and any explanatory text about the waiting list.
STRICT RULES: do NOT type anything in any field, do NOT tick any box, do NOT click any submit/register/pay button.
Only select the race in the dropdown and read. Then answer."""


class WaitlistCheck(BaseModel):
    race_selected: bool
    page_kind: str  # registration_form | sold_out_message | waitlist_form | other
    heading: str
    waitlist_text: str
    required_fields: list[str]
    sold_out_banner: str
    current_url: str


def quota(key: str) -> dict:
    return httpx.get(QUOTA_URL, headers={"Authorization": f"Bearer {key}"}, timeout=10).json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/h_lisbon_waitlist.json")
    a = ap.parse_args()
    key = os.environ.get("HAI_API_KEY")
    if not key:
        sys.exit("HAI_API_KEY manquante")
    waited = 0
    while (q := quota(key))["available"] < 1:
        if waited >= 600:
            sys.exit(f"quota H indisponible après 10 min : {q}")
        print("quota plein, attente 60 s", q, flush=True)
        time.sleep(60)
        waited += 60
    record: dict = {"quota_before": q, "waited_s": waited, "url": URL}
    client = Client()
    handle = None
    t0 = time.perf_counter()
    try:
        handle = client.start_session(agent="h/web-surfer-pro", messages=TASK, answer_schema=WaitlistCheck,
                                      max_steps=30, max_time_s=480)
        record["session_id"] = handle.id
        print("session", handle.id, flush=True)
        res = handle.wait_for_completion(timeout_seconds=540)
        record.update(status=str(res.status), outcome=str(res.outcome), error=res.error,
                      answer=res.answer.model_dump() if isinstance(res.answer, BaseModel) else res.answer,
                      n_events=len(res.events or []))
    finally:
        record["duration_s"] = round(time.perf_counter() - t0, 1)
        if handle is not None:
            try:
                handle.cancel()
                record["cancelled"] = True
            except Exception as e:  # noqa: BLE001 — déjà terminée : l'API peut refuser l'annulation
                record["cancelled"] = f"cancel error: {type(e).__name__}"
        record["quota_after"] = quota(key)
        Path(a.out).write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(record, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
