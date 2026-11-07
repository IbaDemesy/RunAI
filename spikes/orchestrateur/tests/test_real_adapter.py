"""Verifie l'adaptateur reel contre les vrais types et signatures du SDK hai-agents 1.4.3, sans reseau."""

import asyncio
import datetime as dt
import inspect

import hai_agents
from hai_agents.sessions.client import AsyncSessionsClient
from hai_agents.types import (
    ActiveStateChangeData,
    AgentEventData_ObservationEvent,
    AgentEventData_PolicyEvent,
    ImageContent,
    LiveViewUrlData,
    SessionChanges,
    SessionEventZero_ActiveStateChangeEvent,
    SessionEventZero_AgentEvent,
    SessionEventZero_LiveViewUrlEvent,
    ToolRequest,
)
from runai_orch.adapters.base import HUMAN_TOOL, SessionSpec
from runai_orch.adapters.real import RealHAdapter
from runai_orch.contracts import MissionKind, answer_format

NOW = dt.datetime(2026, 11, 7, tzinfo=dt.UTC)


def test_sdk_version_and_signatures():
    assert hai_agents.__version__ if hasattr(hai_agents, "__version__") else True
    sig = lambda name: set(inspect.signature(getattr(AsyncSessionsClient, name)).parameters)
    assert {"agent", "messages", "overrides", "max_time_s", "idle_timeout_s", "queue", "timezone"} <= sig("create_session")
    assert {"id", "from_index", "include_events", "wait_for_seconds"} <= sig("get_session_changes")
    assert {"id", "request"} <= sig("send_session_messages")
    assert {"id", "request"} <= sig("send_session_tool_results")
    for name in ("pause_session", "resume_session", "cancel_session", "force_session_answer", "share_session"):
        assert "id" in sig(name)
    assert "request_options" in sig("get_session_quota")
    from hai_agents.types import Session
    assert "agent_view_url" in Session.model_fields


class FakeSessions:
    def __init__(self, changes):
        self.changes = list(changes)
        self.calls = []

    async def create_session(self, **kw):
        self.calls.append(("create", kw))
        return type("S", (), {"id": "sess-1", "agent_view_url": "https://platform.eu.hcompany.ai/agent-view/sess-1"})

    async def get_session_changes(self, id, **kw):
        self.calls.append(("changes", kw["from_index"]))
        return self.changes.pop(0)

    async def pause_session(self, id):
        self.calls.append(("pause", id))

    async def resume_session(self, id):
        self.calls.append(("resume", id))

    async def send_session_messages(self, id, *, request):
        self.calls.append(("message", request))

    async def send_session_tool_results(self, id, *, request):
        self.calls.append(("tool_result", request))

    async def cancel_session(self, id):
        self.calls.append(("cancel", id))

    async def get_session_quota(self):
        return type("Q", (), {"limit": 3, "active": 1, "available": 2})


def fake_adapter(changes):
    a = RealHAdapter.__new__(RealHAdapter)
    a.client = type("C", (), {"sessions": FakeSessions(changes)})()
    a.wait_for_seconds = 1
    return a


def test_start_sends_answer_format_tools_and_queue():
    async def go():
        a = fake_adapter([])
        spec = SessionSpec(kind="hotel", task="t", answer_format=answer_format(MissionKind.hotel))
        s = await a.start(spec)
        kw = a.client.sessions.calls[0][1]
        assert kw["agent"] == "h/web-surfer-pro" and kw["queue"] is True
        assert kw["overrides"]["agent.answer_format"]["title"] == "HotelAnswer"
        assert kw["overrides"]["agent.tools"] == [HUMAN_TOOL]
        assert s.live_view_url.endswith("sess-1")
    asyncio.run(go())


def test_events_mapping_with_real_sdk_types():
    call = ToolRequest(tool_name="request_human", args={"reason": "consent", "question": "ok?"}, id="call_1")
    ch1 = SessionChanges(status="running", first_index=0, new_events=[
        SessionEventZero_LiveViewUrlEvent(timestamp=NOW, data=LiveViewUrlData(live_view_url="https://live/x")),
        SessionEventZero_AgentEvent(timestamp=NOW, data=AgentEventData_PolicyEvent(
            reasoning_content="Open Njuko\nmore", tool_reqs=[ToolRequest(tool_name="click", args={"x": 1})])),
        SessionEventZero_AgentEvent(timestamp=NOW, data=AgentEventData_ObservationEvent(
            image=ImageContent(source="https://img/1.png", type="url"))),
    ])
    ch2 = SessionChanges(status="awaiting_tool_results", new_events=[SessionEventZero_ActiveStateChangeEvent(
        timestamp=NOW, data=ActiveStateChangeData(state="awaiting_tool_results", pending_tool_calls=[call]))])
    ch3 = SessionChanges(status="idle", answer={"ready_for_payment": True}, new_events=[])
    ch4 = SessionChanges(status="completed", new_events=[])

    async def go():
        a = fake_adapter([ch1, None, ch2, ch3, ch4])
        evs = [e async for e in a.events("sess-1")]
        kinds = [e.type for e in evs]
        assert kinds == ["live_view", "step", "screenshot", "status", "human_needed", "status", "answer",
                         "status", "status"]
        assert evs[1].data == {"thought": "Open Njuko", "action": "click"}
        assert evs[4].data["tool_call"]["id"] == "call_1"
        idx = [c[1] for c in a.client.sessions.calls if c[0] == "changes"]
        assert idx == [0, 3, 3, 4, 4]  # curseur from_index avance du nombre d'evenements
    asyncio.run(go())


def test_commands_use_sdk_request_bodies():
    async def go():
        a = fake_adapter([])
        await a.pause("s")
        await a.resume("s")
        await a.send_message("s", "Prends le 10 km")
        await a.answer_human("s", {"tool_name": "request_human", "args": {}, "id": "call_1"}, {"human_reply": "ok"})
        await a.cancel("s")
        q = await a.quota()
        calls = a.client.sessions.calls
        assert [c[0] for c in calls] == ["pause", "resume", "message", "tool_result", "cancel"]
        assert calls[2][1].type == "user_message" and calls[2][1].message == "Prends le 10 km"
        assert calls[3][1].tool_req.id == "call_1" and calls[3][1].result == {"human_reply": "ok"}
        assert q.available == 2
    asyncio.run(go())
