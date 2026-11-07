"""Agent H 'eclaireur' : recupere le trace officiel (KML/GPX) et les ravitos d'une course.

Le fichier telecharge par l'agent est lu dans ~/Downloads du navigateur cloud H via
session_files.read_file, pendant que la session attend le resultat de l'outil
custom `trace_telecharge` (le navigateur reste donc vivant).

Usage : HAI_API_KEY=... python spikes/survol/eclaireur_h.py lisbonne
"""

import base64
import json
import sys
import time
from pathlib import Path

from hai_agents import Client
from hai_agents.core.api_error import ApiError
from hai_agents.types import ToolRequest, ToolResultEvent

DATA = Path(__file__).parent / "data"
TERMINAL = {"completed", "failed", "timed_out", "interrupted", "cancelled"}

COURSES = {
    "lisbonne": {
        "url": "https://maratonaclubedeportugal.com/en/corrida-marco/edp-lisbon-half-marathon/",
        "nom": "EDP Lisbon Half Marathon 2027 (21.1 km)",
    },
    "milan": {
        "url": "https://www.milanomarathon.it/wizz-air-milano-marathon/percorso/",
        "nom": "Wizz Air Milano Marathon 2027 (42.195 km)",
    },
}

TOOLS = [
    {
        "name": "trace_telecharge",
        "description": (
            "Call this right after the course file (.kml, .kmz or .gpx) has finished "
            "downloading into ~/Downloads. It hands the file over to RunAI."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom_fichier": {
                    "type": "string",
                    "description": "file name in ~/Downloads",
                },
                "url_source": {"type": "string", "description": "URL of the map page"},
            },
            "required": ["nom_fichier", "url_source"],
        },
    }
]

ANSWER = {
    "type": "object",
    "properties": {
        "statut": {"type": "string", "enum": ["ok", "partiel", "echec"]},
        "url_carte": {"type": ["string", "null"]},
        "fichier": {"type": ["string", "null"]},
        "edition_carte": {
            "type": ["string", "null"],
            "description": "year/title shown on the map",
        },
        "ravitos": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "km": {"type": ["number", "null"]},
                    "libelle": {"type": "string"},
                },
                "required": ["libelle"],
            },
        },
        "source_ravitos": {"type": ["string", "null"]},
        "remarque": {"type": ["string", "null"]},
    },
    "required": ["statut"],
}


def prompt(c):
    return f"""You are RunAI's course scout. Race: {c["nom"]}.
1. Open {c["url"]} (official race page) and find the course map (course / percurso section).
2. Get the official course trace as a FILE. If it is a Google My Maps map: open the map in
   full Google My Maps (button 'View larger map' or the map title), open the 3-dots menu of
   the map, choose 'Download KML', tick 'Export to a .KML file instead of KMZ', then Download.
   If the page offers a GPX/KML link directly, download it.
3. When the file is in ~/Downloads, call the tool trace_telecharge(nom_fichier, url_source).
4. Find the water / refreshment stations (km and what is served): on the map legend,
   on the race page, or in the race regulation / FAQ.
Rules: never sign in, never create an account, never fill any form, never pay.
If a step is impossible, skip it and say why in 'remarque'. Answer in the requested JSON."""


def wait_quota(client):
    for i in range(11):
        q = client.sessions.get_session_quota()
        print(
            f"[quota] limit={q.limit} active={q.active} available={q.available}",
            flush=True,
        )
        if q.available and q.available > 0:
            return i * 60
        time.sleep(60)
    raise SystemExit("quota H indisponible apres 10 min")


def handle_tool(client, sid, call, log):
    args = call.args or {}
    t0 = time.time()
    try:
        listing = client.session_files.list_files(sid, path="~/Downloads")
        files = [f for f in listing.files if not f.is_dir]
        log["downloads_listing"] = [
            {"name": f.name, "size": f.size_bytes} for f in files
        ]
        wanted = args.get("nom_fichier", "")
        match = [f for f in files if f.name == wanted] or [
            f for f in files if f.name.lower().endswith((".kml", ".kmz", ".gpx"))
        ]
        if not match:
            return f"ERROR: no .kml/.kmz/.gpx in ~/Downloads (found: {[f.name for f in files]})"
        f = match[0]
        blob = client.session_files.read_file(sid, path=f.path)
        raw = base64.b64decode(blob.content_base64)
        out = DATA / f"trace_h_{f.name}"
        out.write_bytes(raw)
        log["file_saved"] = str(out.name)
        log["file_bytes"] = len(raw)
        log["file_read_s"] = round(time.time() - t0, 2)
        return f"OK, RunAI received {f.name} ({len(raw)} bytes). Continue with step 4."
    except ApiError as e:
        return f"ERROR reading file: {e.status_code}"


def main(course_key):
    c = COURSES[course_key]
    client = Client()
    log = {"course": course_key, "url": c["url"]}
    log["quota_wait_s"] = wait_quota(client)
    t0 = time.time()
    s = client.sessions.create_session(
        agent="h/web-surfer-pro",
        messages=prompt(c),
        max_steps=90,
        max_time_s=720,
        overrides={"agent.tools": TOOLS, "agent.answer_format": ANSWER},
    )
    sid = s.id
    log["session_id"] = sid
    print(f"[h] session {sid}", flush=True)
    answered = set()
    try:
        while True:
            st = client.sessions.get_session_status(sid)
            for call in st.pending_tool_calls or []:
                key = call.id or json.dumps(call.args, sort_keys=True)
                if key in answered:
                    continue
                answered.add(key)
                log.setdefault("tool_calls", []).append(
                    {"t_s": round(time.time() - t0, 1), "args": call.args}
                )
                res = handle_tool(client, sid, call, log)
                print(f"[tool] {call.tool_name} {call.args} -> {res}", flush=True)
                client.sessions.send_session_tool_results(
                    sid,
                    request=ToolResultEvent(
                        kind="tool_result",
                        tool_req=ToolRequest(
                            tool_name=call.tool_name, args=call.args, id=call.id
                        ),
                        result=res,
                    ),
                )
            print(
                f"[h] t={time.time() - t0:5.0f}s status={st.status} steps={st.steps}",
                flush=True,
            )
            if st.status in TERMINAL:
                break
            time.sleep(4)
        log["status"] = st.status
        log["steps"] = st.steps
        log["duration_s"] = round(time.time() - t0, 1)
        log["usage"] = [u.dict() for u in (st.usage_per_model or [])]
        full = client.sessions.get_session(sid)
        log["answer"] = full.latest_answer
    finally:
        try:
            client.sessions.cancel_session(sid)
            log["cancelled"] = True
        except ApiError as e:
            log["cancelled"] = f"cancel -> {e.status_code} (deja termine ?)"
        out = DATA / f"h_run_{course_key}_{sid[:8]}.json"
        out.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str))
        print(json.dumps(log, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "lisbonne")
