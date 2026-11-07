import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from hai_agents.errors import TooManyRequestsError

from runai.h import (
    HAccount,
    HQuotaTimeout,
    HRunner,
    HStep,
    api_keys_from_env,
    build_step_result,
)
from runai.h.events import compact, event_label, event_summary
from runai.models import StepKind, StepStatus, StopPoint
from runai.safety import STOP_INSTRUCTIONS, guard_task
from runai.tracing import TraceWriter

LIVE = "https://live.hcompany.ai/view/abc"
VIEW = "https://platform.hcompany.ai/agents/sessions/s1"


def scripted_events(answer="The page title is Example Domain"):
    return [
        {"type": "LiveViewUrlEvent", "data": {"live_view_url": LIVE}},
        {
            "type": "AgentEvent",
            "data": {
                "kind": "observation_event",
                "image": {"type": "url", "source": "https://x/screenshot.png"},
                "metadata": {"url": "https://example.com/", "title": "Example Domain", "text": "x" * 2000},
            },
        },
        {"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": 2, "total_cost": 0.01}}},
        {"type": "AgentEvent", "data": {"kind": "answer_event", "answer": answer, "outcome": "success"}},
    ]


class FakeSessions:
    def __init__(self, events=None, final_status="completed", quotas=None, create_errors=0):
        self.events = scripted_events() if events is None else events
        self.final_status = final_status
        self.quotas = list(quotas or [])
        self.create_errors = create_errors
        self.created = []
        self.calls = []
        self.served = {}
        self.active = 0
        self.max_active = 0
        self.idle_polls = {}

    async def get_session_quota(self):
        available = self.quotas.pop(0) if self.quotas else 3
        return SimpleNamespace(scope="org", limit=3, active=3 - available, available=available)

    async def create_session(self, **params):
        if self.create_errors:
            self.create_errors -= 1
            raise TooManyRequestsError(body=None)
        self.created.append(params)
        session_id = f"s{len(self.created)}"
        self.served[session_id] = False
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return SimpleNamespace(id=session_id, agent_view_url=VIEW, status=SimpleNamespace(status="pending"))

    async def get_session_changes(self, session_id, from_index=0, include_events=True, wait_for_seconds=0):
        await asyncio.sleep(0)
        if self.served[session_id]:
            return None
        self.served[session_id] = True
        return SimpleNamespace(new_events=self.events, first_index=from_index, answer=None)

    async def get_session_status(self, session_id):
        if self.idle_polls.get(session_id, 0) and self.served[session_id]:
            self.idle_polls[session_id] -= 1
            return SimpleNamespace(status="idle", outcome=None, error=None, steps=2)
        status = self.final_status if self.served[session_id] else "running"
        if self.served[session_id] and status in ("completed", "failed", "interrupted"):
            self.active = max(0, self.active - 1)
        return SimpleNamespace(status=status, outcome=None, error=None, steps=2)

    async def get_session(self, session_id):
        return SimpleNamespace(latest_answer=None, agent_view_url=VIEW)

    async def pause_session(self, session_id):
        self.calls.append(("pause", session_id))

    async def resume_session(self, session_id):
        self.calls.append(("resume", session_id))

    async def send_session_messages(self, session_id, request):
        self.calls.append(("message", session_id, request.message))

    async def cancel_session(self, session_id):
        self.calls.append(("cancel", session_id))

    async def force_session_answer(self, session_id):
        self.calls.append(("force_answer", session_id))


def make_runner(tmp_path, sessions, **kwargs):
    kwargs.setdefault("quota_poll_s", 0)
    return HRunner(SimpleNamespace(sessions=sessions), traces_dir=tmp_path, **kwargs)


def test_run_guards_task_and_returns_step_result(tmp_path):
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)
    seen = []

    result = asyncio.run(
        runner.run(StepKind.search, "Lis le titre", start_url="https://example.com", max_steps=5, on_event=seen.append)
    )

    params = sessions.created[0]
    assert params["agent"] == "h/web-surfer-pro"
    assert params["messages"].endswith(STOP_INSTRUCTIONS)
    assert params["queue"] is False
    assert params["max_steps"] == 5
    assert params["overrides"] == {"agent.environments[kind=web].start_url": "https://example.com"}
    assert result.status is StepStatus.completed
    assert result.summary == "The page title is Example Domain"
    assert str(result.live_view_url) == LIVE
    assert str(result.url) == "https://example.com/"
    assert result.h_session_id == "s1"
    assert result.data["title"] == "Example Domain"
    assert result.data["steps"] == 2
    assert result.data["agent_view_url"] == VIEW
    assert len(seen) == 4


def test_every_event_is_traced_without_screenshots(tmp_path):
    runner = make_runner(tmp_path, FakeSessions())
    asyncio.run(runner.run(StepKind.search, "Lis le titre", mission_id="m1"))

    events = TraceWriter("m1", traces_dir=tmp_path).read()
    types = [event.type for event in events]
    assert types[0] == "session_created"
    assert types[-1] == "result"
    assert "LiveViewUrlEvent" in types
    assert "AgentEvent.answer_event" in types
    observation = next(e for e in events if e.type == "AgentEvent.observation_event")
    assert "image" not in observation.data["event"]["data"]
    assert len(observation.data["event"]["data"]["metadata"]["text"]) <= 501
    assert observation.message == "Example Domain — https://example.com/"


def test_answer_reaching_payment_is_stop_point(tmp_path):
    runner = make_runner(tmp_path, FakeSessions(events=scripted_events("Stopped on the payment page, card number required")))
    result = asyncio.run(runner.run(StepKind.registration, "Prépare l'inscription"))
    assert result.status is StepStatus.stopped_before_commitment
    assert result.stop_point is StopPoint.payment


def test_failed_session(tmp_path):
    runner = make_runner(tmp_path, FakeSessions(events=[], final_status="failed"))
    result = asyncio.run(runner.run(StepKind.search, "x"))
    assert result.status is StepStatus.failed
    assert result.error == "failed"


def test_controls_are_forwarded_and_traced(tmp_path):
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        run = await runner.start(StepKind.accommodation, "Cherche un hôtel", mission_id="m2")
        await run.pause()
        await run.resume()
        await run.send_message("Plutôt près du départ")
        await run.force_answer()
        await run.cancel()
        return await run.wait()

    asyncio.run(scenario())
    assert sessions.calls == [
        ("pause", "s1"),
        ("resume", "s1"),
        ("message", "s1", guard_task("Plutôt près du départ")),
        ("force_answer", "s1"),
        ("cancel", "s1"),
    ]
    controls = [e.message for e in TraceWriter("m2", traces_dir=tmp_path).read() if e.type == "control"]
    assert controls == ["pause", "resume", "message", "force_answer", "cancel"]


def test_waits_for_free_quota_slot(tmp_path):
    sessions = FakeSessions(quotas=[0, 0, 1])
    runner = make_runner(tmp_path, sessions)
    result = asyncio.run(runner.run(StepKind.search, "x"))
    assert result.status is StepStatus.completed
    assert sessions.quotas == []


def test_quota_timeout(tmp_path):
    sessions = FakeSessions(quotas=[0] * 100)
    runner = make_runner(tmp_path, sessions, quota_timeout_s=0)
    with pytest.raises(HQuotaTimeout):
        asyncio.run(runner.run(StepKind.search, "x"))
    assert sessions.created == []
    assert runner.accounts[0].active == 0


def test_retries_when_create_hits_429(tmp_path):
    sessions = FakeSessions(create_errors=1)
    result = asyncio.run(make_runner(tmp_path, sessions).run(StepKind.search, "x"))
    assert result.status is StepStatus.completed
    assert len(sessions.created) == 1


def test_run_many_respects_local_concurrency(tmp_path):
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions, max_concurrency=1)
    steps = [HStep(StepKind.registration, "a"), HStep(StepKind.accommodation, "b"), HStep(StepKind.transport, "c")]

    results = asyncio.run(runner.run_many(steps, mission_id="m3"))

    assert [r.kind for r in results] == [StepKind.registration, StepKind.accommodation, StepKind.transport]
    assert all(r.status is StepStatus.completed for r in results)
    assert sessions.max_active == 1


def test_run_many_turns_launch_errors_into_failed_results(tmp_path):
    runner = make_runner(tmp_path, FakeSessions(quotas=[0] * 100), quota_timeout_s=0)
    results = asyncio.run(runner.run_many([HStep(StepKind.transport, "x")]))
    assert results[0].status is StepStatus.failed
    assert "HQuotaTimeout" in results[0].error


def test_timeout_cancels_session(tmp_path):
    class Stuck(FakeSessions):
        async def get_session_changes(self, *args, **kwargs):
            await asyncio.sleep(10)

    sessions = Stuck()
    runner = make_runner(tmp_path, sessions)
    result = asyncio.run(runner.run(StepKind.search, "x", timeout_s=0.05))
    assert result.status is StepStatus.failed
    assert "timeout" in result.error
    assert ("cancel", "s1") in sessions.calls
    assert runner.accounts[0].active == 0


def test_build_step_result_mapping():
    assert build_step_result(StepKind.search, "paused").status is StepStatus.paused
    assert build_step_result(StepKind.search, "queued").status is StepStatus.pending
    assert build_step_result(StepKind.search, "interrupted").error == "interrupted"
    structured = build_step_result(StepKind.search, "completed", answer={"price": 42})
    assert structured.summary == '{"price": 42}'
    assert build_step_result(StepKind.search, "completed", last_url="not a url").url is None


def test_event_helpers():
    assert event_label({"type": "AgentEvent", "data": {"kind": "policy_event"}}) == "AgentEvent.policy_event"
    assert event_summary({"type": "AgentRunStatusChangeEvent", "data": {"status": "paused"}}) == "paused"
    assert compact({"image": "x", "page_html": "y", "a": [{"image": 1, "b": 2}]}) == {"a": [{"b": 2}]}


def test_one_shot_waits_past_transient_idle(tmp_path):
    sessions = FakeSessions()
    sessions.idle_polls = {"s1": 2}
    result = asyncio.run(make_runner(tmp_path, sessions).run(StepKind.search, "x"))
    assert result.data["h_status"] == "completed"
    assert sessions.idle_polls == {"s1": 0}


def test_interactive_session_settles_on_idle(tmp_path):
    sessions = FakeSessions()
    sessions.idle_polls = {"s1": 5}
    result = asyncio.run(make_runner(tmp_path, sessions).run(StepKind.search, "x", idle_timeout_s=60))
    assert sessions.created[0]["idle_timeout_s"] == 60
    assert result.data["h_status"] == "idle"
    assert result.status is StepStatus.completed


def make_accounts(tmp_path, *sessions, cap=3, **kwargs):
    kwargs.setdefault("quota_poll_s", 0)
    accounts = [
        HAccount(f"k{i}", client=SimpleNamespace(sessions=s), max_concurrency=cap) for i, s in enumerate(sessions, 1)
    ]
    return HRunner(accounts=accounts, traces_dir=tmp_path, **kwargs)


def test_api_keys_from_env(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "a")
    monkeypatch.setenv("HAI_API_KEY_2", "b")
    monkeypatch.delenv("HAI_API_KEY_3", raising=False)
    assert api_keys_from_env() == [("HAI_API_KEY", "a"), ("HAI_API_KEY_2", "b")]
    monkeypatch.delenv("HAI_API_KEY")
    assert api_keys_from_env() == [("HAI_API_KEY_2", "b")]
    runner = HRunner(traces_dir=Path("."))
    assert [a.name for a in runner.accounts] == ["HAI_API_KEY_2"]


def test_pool_picks_key_with_most_free_slots(tmp_path):
    first, second = FakeSessions(quotas=[1]), FakeSessions(quotas=[3])
    runner = make_accounts(tmp_path, first, second)
    result = asyncio.run(runner.run(StepKind.search, "x", mission_id="pool"))
    assert result.status is StepStatus.completed
    assert (len(first.created), len(second.created)) == (0, 1)
    created = TraceWriter("pool", traces_dir=tmp_path).read()[0]
    assert created.data["h_key"] == "k2"


def test_pool_spreads_run_many_under_per_key_cap(tmp_path):
    first, second = FakeSessions(), FakeSessions()
    runner = make_accounts(tmp_path, first, second, cap=1)
    steps = [HStep(StepKind.registration, "a"), HStep(StepKind.accommodation, "b"), HStep(StepKind.transport, "c")]
    results = asyncio.run(runner.run_many(steps))
    assert all(r.status is StepStatus.completed for r in results)
    assert first.max_active == second.max_active == 1
    assert len(first.created) + len(second.created) == 3
    assert [a.active for a in runner.accounts] == [0, 0]


def test_pool_skips_full_key(tmp_path):
    full, free = FakeSessions(quotas=[0] * 10), FakeSessions(quotas=[0, 2])
    result = asyncio.run(make_accounts(tmp_path, full, free).run(StepKind.search, "x"))
    assert result.status is StepStatus.completed
    assert full.created == [] and len(free.created) == 1


def test_reserved_create_params_cannot_bypass_guard(tmp_path):
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)
    for key in ("messages", "agent", "queue"):
        with pytest.raises(ValueError):
            asyncio.run(runner.start(StepKind.search, "x", **{key: "y"}))
    assert sessions.created == []


def test_run_many_shared_options(tmp_path):
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)
    steps = [HStep(StepKind.search, "a"), HStep(StepKind.search, "b", max_steps=3)]
    results = asyncio.run(runner.run_many(steps, max_steps=10, start_url="https://example.com"))
    assert all(r.status is StepStatus.completed for r in results)
    assert sorted(p["max_steps"] for p in sessions.created) == [3, 10]
    assert all("overrides" in p for p in sessions.created)


def test_interactive_idle_keeps_slot_until_close(tmp_path):
    sessions = FakeSessions()
    sessions.idle_polls = {"s1": 5}
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        run = await runner.start(StepKind.search, "x", idle_timeout_s=60)
        result = await run.wait()
        assert runner.accounts[0].active == 1
        await run.close()
        return result

    assert asyncio.run(scenario()).data["h_status"] == "idle"
    assert ("cancel", "s1") in sessions.calls
    assert runner.accounts[0].active == 0


def test_trace_failure_cancels_created_session(tmp_path):
    class BrokenTrace:
        def write(self, event):
            raise OSError("disk full")

    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)
    with pytest.raises(OSError):
        asyncio.run(runner.start(StepKind.search, "x", trace=BrokenTrace()))
    assert ("cancel", "s1") in sessions.calls
    assert runner.accounts[0].active == 0


def test_cancelled_wait_cancels_session(tmp_path):
    class Stuck(FakeSessions):
        async def get_session_changes(self, *args, **kwargs):
            await asyncio.sleep(10)

    sessions = Stuck()
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        task = asyncio.create_task(runner.run(StepKind.search, "x"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert ("cancel", "s1") in sessions.calls
    assert runner.accounts[0].active == 0


def test_step_count_follows_status(tmp_path):
    class Final(FakeSessions):
        async def get_session_status(self, session_id):
            status = await super().get_session_status(session_id)
            status.steps = 7
            return status

    result = asyncio.run(make_runner(tmp_path, Final()).run(StepKind.search, "x"))
    assert result.data["steps"] == 7


def test_pool_tie_prefers_least_loaded_org(tmp_path):
    first, second = FakeSessions(quotas=[2]), FakeSessions(quotas=[3])
    asyncio.run(make_accounts(tmp_path, first, second, cap=1).run(StepKind.search, "x"))
    assert (len(first.created), len(second.created)) == (0, 1)


def test_trace_failure_while_following_releases_slot(tmp_path):
    class FlakyTrace:
        writes = 0

        def write(self, event):
            self.writes += 1
            if self.writes > 1:
                raise OSError("disk full")

    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        run = await runner.start(StepKind.search, "x", trace=FlakyTrace())
        with pytest.raises(OSError):
            await run.wait()

    asyncio.run(scenario())
    assert ("cancel", "s1") in sessions.calls
    assert runner.accounts[0].active == 0


def test_concurrent_launches_use_other_free_key(tmp_path):
    first, second = FakeSessions(), FakeSessions(quotas=[2] * 10)
    runner = make_accounts(tmp_path, first, second, cap=1, quota_timeout_s=0)

    async def scenario():
        return await asyncio.gather(runner.start(StepKind.search, "a"), runner.start(StepKind.search, "b"))

    runs = asyncio.run(scenario())
    assert sorted(run.account.name for run in runs) == ["k1", "k2"]


def test_429_retry_waits_poll_interval(tmp_path):
    sessions = FakeSessions(create_errors=1)
    runner = make_runner(tmp_path, sessions, quota_poll_s=0.2)

    async def scenario():
        started = asyncio.get_running_loop().time()
        await runner.run(StepKind.search, "x")
        return asyncio.get_running_loop().time() - started

    assert asyncio.run(scenario()) >= 0.2
