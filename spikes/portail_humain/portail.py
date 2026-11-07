"""Spike RunAI : « l'agent remplit, l'humain signe ».

Un agent H (h/web-surfer-pro) remplit une inscription Njuko. Avant chaque case
sensible il demande une validation humaine :

- mode ``tool``    : outil client ``demander_validation_humaine`` -> la session
  passe en ``awaiting_tool_results`` -> le portail renvoie un tool result ;
- mode ``message`` : l'agent termine son tour par une question
  ``VALIDATION_REQUISE {...}`` -> session ``idle`` -> le portail répond par
  ``send_message``.

Le portail (FastAPI) affiche la capture courante et le texte de la case ; le
clic « Je valide » / « Je refuse » est renvoyé à l'agent. Les délais sont
journalisés dans ``runs/<session>.jsonl``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
TOOL_NAME = "demander_validation_humaine"
MARKER = "VALIDATION_REQUISE"

DEFAULT_URL = "https://in.njuko.com/wizz-air-milano-marathon-20271776152378557"

PERSONA = (
    "Camille Martin, female, born 12/05/1994, French nationality, country of residence France, "
    "email camille.martin@example.com, phone +33 6 12 34 56 78, emergency contact Paul Martin "
    "+33 6 98 76 54 32, t-shirt size M, first marathon: yes, no qualifying time, no running club, "
    "no federation licence."
)

SENSITIVE = (
    "health / medical certificate / PPS / fitness declaration, race regulation or terms acceptance, "
    "personal data / GDPR / marketing / profiling / third-party consent, image rights, insurance, "
    "file upload, or anything related to payment"
)

COMMON_RULES = f"""
HARD RULES (never break them):
1. This is a test with a fictitious person. Never pay, never enter card details, never create an
   account, never click the final payment / order / confirm button. Stop on the page right before
   payment and give your final answer there.
2. Fill ordinary fields (name, birth date, phone, size...) yourself with the persona data.
3. SENSITIVE BOXES: before ticking, selecting or answering ANY checkbox / radio / upload about
   {SENSITIVE}, you MUST ask the human first (see HOW TO ASK). Do not touch that box before the answer.
   One request per box. Exception: a numbered list of optional marketing / data-sharing consents
   shown together may be sent as ONE request (texte = all items).
4. After the answer:
   - "APPROUVE": apply the box exactly as approved (tick it / choose the accepting option).
   - "REFUSE" on an OPTIONAL consent: choose the refusing option (No / Non / Je refuse) and continue.
   - "REFUSE" on a MANDATORY box (regulation, required declaration): do not tick it, do not look for
     a workaround, stop and give your final answer explaining the registration is blocked by the
     human refusal.
5. You have no file to upload. If an upload is mandatory, ask the human (categorie "sante"), then
   stop if it cannot be skipped.
"""

TASK_TOOL = f"""You fill a race registration form on behalf of a test persona.
Go to {{url}} and start an individual registration for the marathon (the main 42 km race).
Persona: {PERSONA}
{COMMON_RULES}
HOW TO ASK: call the tool `{TOOL_NAME}` with categorie (one of: sante, reglement, rgpd, droit_image,
assurance, paiement, autre), champ (short label of the box), texte (verbatim text of the box, up to
600 characters), obligatoire (true/false as shown on the page). Wait for its result and follow it.
Final answer: the page you stopped on, what you filled, each human decision and what you did after it.
"""

TASK_MESSAGE = f"""You fill a race registration form on behalf of a test persona.
Go to {{url}} and start an individual registration for the marathon (the main 42 km race).
Persona: {PERSONA}
{COMMON_RULES}
HOW TO ASK: you have no tool for this. To ask, END YOUR TURN with an answer that starts with the
exact word {MARKER} followed by one JSON object on a single line, e.g.
{MARKER} {{{{"categorie": "reglement", "champ": "...", "texte": "...", "obligatoire": true}}}}
categorie is one of: sante, reglement, rgpd, droit_image, assurance, paiement, autre; texte is the
verbatim text of the box (up to 600 characters). Keep the browser on the same page: the human will
answer with a message "APPROUVE ..." or "REFUSE ...", then continue the registration from there.
When you are finally stopped (page before payment, or blocked), give a final answer that does NOT
start with {MARKER}: the page you stopped on, what you filled, each human decision and what you did.
"""


def now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    return None if ts is None else dt.datetime.fromtimestamp(ts, dt.UTC).isoformat(timespec="milliseconds")


class Portal:
    """État partagé entre le runner H et les routes HTTP."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode = "tool"
        self.session_id: str | None = None
        self.status = "init"
        self.live_view_url: str | None = None
        self.last_screenshot: dict[str, Any] | None = None
        self.last_thought = ""
        self.pending: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.answer: Any = None
        self.notes: list[str] = []
        self.log_path: Path | None = None
        self.client: Any = None
        self.event_count = 0

    def log(self, kind: str, **data: Any) -> None:
        record = {"t": iso(now()), "kind": kind, **data}
        if self.log_path:
            with self.log_path.open("a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        print(f"[{record['t']}] {kind} {json.dumps(data, ensure_ascii=False, default=str)[:300]}", flush=True)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            pending = None
            if self.pending:
                pending = {k: v for k, v in self.pending.items() if k not in ("call", "image_bytes")}
            return {
                "mode": self.mode,
                "session_id": self.session_id,
                "status": self.status,
                "live_view_url": self.live_view_url,
                "last_thought": self.last_thought[-400:],
                "pending": pending,
                "history": [{k: v for k, v in h.items() if k not in ("call", "image_bytes")} for h in self.history],
                "answer": self.answer,
                "notes": self.notes,
                "event_count": self.event_count,
            }


PORTAL = Portal()


def fetch_image(source: str) -> bytes | None:
    """Télécharge la capture H (URL authentifiée -> redirection S3 présignée)."""
    if source.startswith("data:") or not source.startswith("http"):
        import base64

        return base64.b64decode(source.split(",", 1)[-1])
    headers = {}
    if "hcompany.ai" in source:
        headers["Authorization"] = f"Bearer {os.environ.get('HAI_API_KEY', '')}"
    try:
        r = httpx.get(source, headers=headers, follow_redirects=True, timeout=20)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as exc:
        PORTAL.log("screenshot_error", error=str(exc)[:200])
        return None


def open_request(kind: str, info: dict[str, Any], call: dict[str, Any] | None, raised_at: float) -> None:
    shot = PORTAL.last_screenshot or {}
    image = fetch_image(shot["source"]) if shot.get("source") else None
    req = {
        "id": uuid.uuid4().hex[:8],
        "mechanism": kind,
        "categorie": info.get("categorie"),
        "champ": info.get("champ"),
        "texte": info.get("texte"),
        "obligatoire": info.get("obligatoire"),
        "page_url": shot.get("page_url"),
        "agent_raised_at": iso(raised_at),
        "portal_seen_at": iso(now()),
        "has_screenshot": image is not None,
        "call": call,
        "image_bytes": image,
        "_seen": now(),
        "_raised": raised_at,
    }
    with PORTAL.lock:
        PORTAL.pending = req
    PORTAL.log("validation_requested", **{k: v for k, v in req.items() if k not in ("image_bytes",)})


def decide(req_id: str, decision: str, comment: str = "", source: str = "humain") -> dict[str, Any]:
    with PORTAL.lock:
        req = PORTAL.pending
        if not req or req["id"] != req_id:
            raise HTTPException(409, "Aucune demande en attente avec cet id")
        PORTAL.pending = None
    approved = decision == "approve"
    verdict = "APPROUVE" if approved else "REFUSE"
    text = f"{verdict}: {comment}".strip(": ") if comment else verdict
    t_click = now()
    from hai_agents import ToolRequest, ToolResultEvent

    if req["mechanism"] == "tool":
        call = req["call"]
        PORTAL.client.sessions.send_session_tool_results(
            PORTAL.session_id,
            request=ToolResultEvent(
                tool_req=ToolRequest(tool_name=call["tool_name"], args=call.get("args") or {}, id=call.get("id")),
                result={"decision": verdict, "approved": approved, "comment": comment or None},
            ),
        )
    elif req["mechanism"] == "message":
        PORTAL.client.session(PORTAL.session_id).send_message(
            f"{text} (champ: {req.get('champ')}). Continue from the current page following the rules."
        )
    t_sent = now()
    entry = {
        **{k: v for k, v in req.items() if k != "call"},
        "decision": verdict,
        "decided_by": source,
        "human_wait_s": round(t_click - req["_seen"], 2),
        "send_api_s": round(t_sent - t_click, 3),
        "_sent": t_sent,
        "resume_s": None,
        "agent_next_action": None,
    }
    with PORTAL.lock:
        PORTAL.history.append(entry)
    PORTAL.log("decision_sent", id=req_id, decision=verdict, by=source, send_api_s=entry["send_api_s"])
    return {"ok": True, "decision": verdict}


def mark_resume(event_ts: float, what: str) -> None:
    with PORTAL.lock:
        for h in reversed(PORTAL.history):
            if h.get("resume_s") is None and h.get("_sent"):
                h["resume_s"] = round(event_ts - h["_sent"], 2)
                h["resume_seen_s"] = round(now() - h["_sent"], 2)
                h["resume_event"] = what
                PORTAL.log("agent_resumed", id=h["id"], resume_s=h["resume_s"], seen_s=h["resume_seen_s"], event=what)
                return


def mark_next_action(event_ts: float, text: str) -> None:
    with PORTAL.lock:
        for h in reversed(PORTAL.history):
            if h.get("agent_next_action") is None and h.get("resume_s") is not None:
                h["agent_next_action"] = text[:400]
                h["next_policy_s"] = round(event_ts - h["_sent"], 2)
                return


def parse_marker(text: str) -> dict[str, Any] | None:
    if MARKER not in text:
        return None
    m = re.search(r"\{.*\}", text.split(MARKER, 1)[1], re.DOTALL)
    if not m:
        return {"champ": "?", "texte": text[:600]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"champ": "?", "texte": m.group(0)[:600]}


def to_dict(obj: Any) -> Any:
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def handle_event(ev: Any) -> None:
    PORTAL.event_count += 1
    ts = ev.timestamp.timestamp() if getattr(ev, "timestamp", None) else now()
    data = to_dict(ev.data)
    etype = ev.type
    if etype == "LiveViewUrlEvent":
        PORTAL.live_view_url = data.get("live_view_url")
        PORTAL.log("live_view", url=PORTAL.live_view_url)
        return
    if etype == "ActiveStateChangeEvent":
        state = data.get("state")
        PORTAL.log("active_state", state=state, pending=data.get("pending_tool_calls"))
        if state == "running":
            mark_resume(ts, "ActiveStateChange:running")
        if state == "awaiting_tool_results" and PORTAL.mode == "tool":
            for call in data.get("pending_tool_calls") or []:
                if call.get("tool_name") == TOOL_NAME and not PORTAL.pending:
                    open_request("tool", call.get("args") or {}, call, ts)
        return
    if etype != "AgentEvent" or not isinstance(data, dict):
        PORTAL.log("event", type=etype)
        return
    kind = data.get("kind")
    if kind == "observation_event":
        img = data.get("image") or {}
        meta = data.get("metadata") or {}
        page_url = meta.get("url") or meta.get("page_url") or (meta.get("tab") or {}).get("url")
        if img.get("source"):
            PORTAL.last_screenshot = {"source": img["source"], "page_url": page_url, "t": ts}
        mark_resume(ts, "observation")
    elif kind == "policy_event":
        thought = (data.get("content") or data.get("reasoning_content") or "")[:600]
        tools = [t.get("tool_name") for t in data.get("tool_reqs") or []]
        PORTAL.last_thought = thought
        mark_resume(ts, "policy")
        mark_next_action(ts, f"{thought} -> {tools}")
        PORTAL.log("policy", tools=tools, thought=thought[:250])
    elif kind == "answer_event":
        answer = data.get("answer")
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        PORTAL.log("answer", text=text[:1500])
        info = parse_marker(text) if PORTAL.mode == "message" else None
        if info is not None:
            open_request("message", info, None, ts)
        else:
            PORTAL.answer = text
    elif kind == "tool_result":
        PORTAL.log("tool_result", tool=(data.get("tool_req") or {}).get("tool_name"), result=str(data.get("result"))[:200])
    elif kind == "error_event":
        PORTAL.log("agent_error", error=str(data.get("error"))[:300])


def wait_quota(client: Any, max_wait_s: int = 600) -> None:
    start = now()
    while True:
        q = client.sessions.get_session_quota()
        PORTAL.log("quota", limit=q.limit, active=q.active, available=q.available)
        if q.available > 0:
            return
        if now() - start > max_wait_s:
            raise RuntimeError("Quota H indisponible après 10 min")
        PORTAL.notes.append(f"quota=0 à {iso(now())}, attente 60 s")
        time.sleep(60)


def run_h(args: argparse.Namespace) -> None:
    from hai_agents import Client, tool
    from hai_agents.polling import stream_session

    client = Client()
    PORTAL.client = client
    wait_quota(client)

    @tool(name=TOOL_NAME)
    def ask_human(categorie: str, champ: str, texte: str, obligatoire: bool = False) -> str:
        """Ask the human runner to approve or refuse ONE sensitive box (health / medical certificate, race
        regulation, GDPR / marketing consent, image rights, insurance, upload, payment) BEFORE touching it.
        Returns {"decision": "APPROUVE" | "REFUSE"}."""
        raise RuntimeError("answered by the portal")

    task = (TASK_TOOL if args.mode == "tool" else TASK_MESSAGE).format(url=args.url)
    params: dict[str, Any] = {
        "agent": "h/web-surfer-pro",
        "messages": task,
        "max_steps": args.max_steps,
        "max_time_s": args.max_time,
        "timezone": "Europe/Paris",
        "queue": False,
        "delete_screenshot_after_min": 1440,
    }
    if args.mode == "message":
        params["idle_timeout_s"] = 900
    t0 = now()
    handle = client.start_session(tools=[ask_human] if args.mode == "tool" else None, **params)
    PORTAL.session_id = handle.id
    PORTAL.log_path = RUNS / f"{handle.id}.jsonl"
    PORTAL.log("session_created", id=handle.id, mode=args.mode, url=args.url, create_api_s=round(now() - t0, 2))
    try:
        deadline = t0 + args.max_wall
        last_status = 0.0
        while now() < deadline:
            for ev in stream_session(client, handle.id, until="terminal", wait_for_seconds=10,
                                     timeout_seconds=max(1, deadline - now())):
                handle_event(ev)
                if PORTAL.answer:
                    break
                if now() - last_status > 5:
                    PORTAL.status = handle.status().status
                    last_status = now()
            st = handle.status()
            PORTAL.status = st.status
            if PORTAL.answer or st.status not in ("running", "pending", "awaiting_tool_results", "idle", "paused"):
                break
        else:
            PORTAL.notes.append("max_wall atteint")
    except TimeoutError:
        PORTAL.notes.append("max_wall atteint (timeout stream)")
    except Exception as exc:  # noqa: BLE001
        PORTAL.notes.append(f"erreur runner: {type(exc).__name__}: {exc}")
        PORTAL.log("runner_error", error=f"{type(exc).__name__}: {exc}")
    finally:
        finish(client, handle.id, t0)


def finish(client: Any, sid: str, t0: float) -> None:
    try:
        st = client.sessions.get_session_status(sid)
        usage = [to_dict(u) for u in st.usage_per_model or []]
        PORTAL.log("final_status", status=st.status, steps=st.steps, outcome=st.outcome, usage=usage,
                   wall_s=round(now() - t0, 1))
        if st.status not in ("completed", "failed", "cancelled", "timed_out"):
            client.sessions.cancel_session(sid)
            PORTAL.log("cancelled", id=sid)
    except Exception as exc:  # noqa: BLE001
        PORTAL.log("cancel_error", error=str(exc)[:200])
    PORTAL.status = f"terminé ({PORTAL.status})"
    summary = PORTAL.snapshot()
    (RUNS / f"{sid}.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_mock(args: argparse.Namespace) -> None:
    """Démo sans H : rejoue des demandes fictives (plan B si H tombe)."""
    PORTAL.session_id = "mock"
    PORTAL.log_path = RUNS / "mock.jsonl"
    PORTAL.status = "running"

    class Fake:
        class sessions:
            @staticmethod
            def send_session_tool_results(*_a: Any, **_k: Any) -> None:
                return None

    PORTAL.client = Fake()
    demo = [
        ("reglement", "Règlement et conditions", "Je déclare être majeur(e), accepter le règlement...", True),
        ("rgpd", "Consentements marketing 1-7", "1. Autorisation du traitement de mes données...", False),
        ("sante", "Certificat médical", "Certificat médical (upload)", True),
    ]
    for cat, champ, texte, oblig in demo:
        call = {"tool_name": TOOL_NAME, "id": uuid.uuid4().hex[:6], "args": {}}
        open_request("tool", {"categorie": cat, "champ": champ, "texte": texte, "obligatoire": oblig}, call, now())
        while PORTAL.pending:
            time.sleep(0.3)
        time.sleep(1.0)
        mark_resume(now(), "mock")
    PORTAL.status = "terminé (mock)"
    PORTAL.answer = "Mock : arrêt avant paiement."


def auto_decider(policy: dict[str, str], delay: float) -> None:
    """Décide à la place de l'humain après `delay` s, via la même route HTTP que le bouton."""
    while True:
        time.sleep(0.5)
        req = PORTAL.pending
        if not req or now() - req["_seen"] < delay:
            continue
        cat = (req.get("categorie") or "autre").lower()
        decision = policy.get(cat, policy.get("*", "approve"))
        try:
            r = httpx.post(f"http://127.0.0.1:{ARGS.port}/api/decide",
                           json={"id": req["id"], "decision": decision, "comment": f"auto-policy ({cat})",
                                 "source": "auto"}, timeout=30)
            PORTAL.log("auto_decision", status=r.status_code, decision=decision, categorie=cat)
        except httpx.HTTPError as exc:
            PORTAL.log("auto_decision_error", error=str(exc))


app = FastAPI(title="RunAI portail de validation")


class Decision(BaseModel):
    id: str
    decision: str
    comment: str = ""
    source: str = "humain"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "validation.html").read_text()


@app.get("/api/state")
def state() -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(PORTAL.snapshot(), default=str)))


@app.get("/api/screenshot/{req_id}")
def screenshot(req_id: str) -> Response:
    for req in [PORTAL.pending, *reversed(PORTAL.history)]:
        if req and req["id"] == req_id and req.get("image_bytes"):
            return Response(req["image_bytes"], media_type="image/png")
    raise HTTPException(404)


@app.post("/api/decide")
def post_decide(d: Decision) -> dict[str, Any]:
    if d.decision not in ("approve", "refuse"):
        raise HTTPException(422, "decision = approve | refuse")
    return decide(d.id, d.decision, d.comment, d.source)


ARGS: argparse.Namespace


def main() -> None:
    global ARGS
    load_dotenv(HERE.parents[1] / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["tool", "message", "mock"], default="tool")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--max-steps", type=int, default=120)
    p.add_argument("--max-time", type=float, default=1200)
    p.add_argument("--max-wall", type=float, default=1800, help="garde-fou mur (s) avant cancel")
    p.add_argument("--auto", default="", help='politique auto, ex: "reglement=approve,rgpd=refuse,*=approve"')
    p.add_argument("--auto-delay", type=float, default=20, help="s avant décision auto si aucun clic")
    ARGS = p.parse_args()
    RUNS.mkdir(exist_ok=True)
    PORTAL.mode = "tool" if ARGS.mode == "mock" else ARGS.mode
    if ARGS.auto:
        policy = dict(kv.split("=", 1) for kv in ARGS.auto.split(","))
        threading.Thread(target=auto_decider, args=(policy, ARGS.auto_delay), daemon=True).start()
    target = run_mock if ARGS.mode == "mock" else run_h
    threading.Thread(target=target, args=(ARGS,), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=ARGS.port, log_level="warning")


if __name__ == "__main__":
    main()
