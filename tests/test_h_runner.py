import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from hai_agents.errors import TooManyRequestsError
from hai_agents.tools import tool

from runai.h import (
    HAccount,
    HQuotaTimeout,
    HRunner,
    HStep,
    api_keys_from_env,
    build_step_result,
)
from runai.h.events import compact, event_label, event_summary
from runai.models import StepKind, StepStatus, StopPoint, TraceEvent
from runai.safety import STOP_INSTRUCTIONS, guard_task
from runai.tracing import TraceWriter

LIVE = "https://live.hcompany.ai/view/abc"
VIEW = "https://platform.hcompany.ai/agents/sessions/s1"
SHARE = "https://agp.eu.hcompany.ai/share/api/v1/trajectories/s1"


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
    def __init__(self, events=None, final_status="completed", quotas=None, create_errors=0, error_code=None):
        self.events = scripted_events() if events is None else events
        self.final_status = final_status
        self.error_code = error_code
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

    async def share_session(self, session_id):
        return SimpleNamespace(share_url=f"/share/api/v1/trajectories/{session_id}")

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
        return SimpleNamespace(status=status, outcome=None, error=None, error_code=self.error_code, steps=2)

    async def get_session(self, session_id):
        return SimpleNamespace(
            id=session_id, latest_answer=None, agent_view_url=VIEW
        )

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
    assert len(seen) == 5


@pytest.mark.parametrize("share_url", [SHARE, None])
def test_share_link_absolute_or_empty(tmp_path, share_url):
    class Sessions(FakeSessions):
        async def share_session(self, session_id):
            return SimpleNamespace(share_url=share_url)

    result = asyncio.run(make_runner(tmp_path, Sessions(events=[])).run(StepKind.search, "Read the title"))
    assert result.data["share_url"] == share_url
    assert (str(result.live_view_url) if result.live_view_url else None) == share_url


@pytest.mark.parametrize("base_url", ["https://agp.hcompany.ai", "https://agp.hcompany.ai/api/v1/"])
def test_share_link_uses_client_origin(tmp_path, base_url):
    client = SimpleNamespace(
        sessions=FakeSessions(events=[]),
        _client_wrapper=SimpleNamespace(get_base_url=lambda: base_url),
    )
    runner = HRunner(client, traces_dir=tmp_path, quota_poll_s=0)
    result = asyncio.run(runner.run(StepKind.search, "Read the title"))
    expected = "https://agp.hcompany.ai/share/api/v1/trajectories/s1"
    assert result.data["share_url"] == expected
    assert str(result.live_view_url) == expected


def test_share_failure_is_nonfatal_and_logged(tmp_path):
    class Sessions(FakeSessions):
        async def share_session(self, session_id):
            raise RuntimeError("Sharing unavailable")

    runner = make_runner(tmp_path, Sessions(events=[]))
    result = asyncio.run(runner.run(StepKind.search, "Read the title", mission_id="share-failed"))
    assert result.status is StepStatus.completed
    assert result.data["share_url"] is None
    assert result.live_view_url is None
    events = TraceWriter("share-failed", traces_dir=tmp_path).read()
    assert any(e.type == "warning" and "Sharing unavailable" in e.message for e in events)


@pytest.mark.parametrize("outcome", ["blocked", "infeasible", "partial"])
def test_answer_outcome_mapping(tmp_path, outcome):
    answer = "Stopped on the payment page, card number required"
    events = scripted_events(answer)
    events[-1]["data"]["outcome"] = outcome
    result = asyncio.run(make_runner(tmp_path, FakeSessions(events=events)).run(StepKind.registration, "Prepare registration"))
    assert result.data["outcome"] == outcome
    if outcome == "blocked":
        assert result.status is StepStatus.failed
        assert result.error == "Blocked by the site (captcha/anti-bot or login wall)"
    elif outcome == "infeasible":
        assert result.status is StepStatus.failed
        assert result.data["retryable"] is False
        assert result.error == f"The agent judged the task infeasible: {answer}"
    else:
        assert result.status is StepStatus.stopped_before_commitment
        assert result.stop_point is StopPoint.payment
        assert result.data["partial"] is True


def test_infeasible_answer_is_truncated():
    result = build_step_result(StepKind.search, "completed", outcome="infeasible", answer="x" * 250)
    assert result.error == f"The agent judged the task infeasible: {'x' * 200}"


@pytest.mark.parametrize("error_code", [None, "environment_error", "no_answer", "answer_validation", "timeout", "insufficient_credit", "internal"])
def test_status_error_code_is_exposed(tmp_path, error_code):
    sessions = FakeSessions(events=[], final_status="failed", error_code=error_code)
    result = asyncio.run(make_runner(tmp_path, sessions).run(StepKind.search, "Read the title"))
    assert result.data["error_code"] == error_code
    assert result.error == (error_code or "failed")
    explicit = build_step_result(StepKind.search, "failed", error="Detailed error", error_code=error_code)
    assert explicit.error == "Detailed error"


def test_environment_overrides_merge_with_explicit_values(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_H_OVERRIDES", '{"agent.environments[kind=web].settle_s": 0.5, "agent.environments[kind=web].lazy": true}')
    sessions = FakeSessions()
    runner = make_runner(tmp_path, sessions)
    asyncio.run(runner.run(StepKind.search, "Read the title", start_url="https://example.com", overrides={
        "agent.environments[kind=web].settle_s": 1,
        "agent.environments[kind=web].start_url": "https://other.example",
    }))
    assert sessions.created[0]["overrides"] == {
        "agent.environments[kind=web].settle_s": 1,
        "agent.environments[kind=web].lazy": True,
        "agent.environments[kind=web].start_url": "https://example.com",
    }


@pytest.mark.parametrize("value", ["invalid", "[]", "null", "true"])
def test_invalid_environment_overrides(tmp_path, monkeypatch, value):
    monkeypatch.setenv("RUNAI_H_OVERRIDES", value)
    with pytest.raises(ValueError, match="RUNAI_H_OVERRIDES must be .*JSON object"):
        make_runner(tmp_path, FakeSessions())


def test_guard_task_does_not_duplicate_safety_instructions():
    guarded = guard_task("Lis le titre")
    assert guard_task(guarded) == guarded


def test_h_run_dispatches_async_ask_user_tool_without_blocking(tmp_path):
    class ToolSessionHandle:
        def __init__(self, sessions, session_id, tools):
            self.sessions = sessions
            self.id = session_id
            self.tools = tools

        async def stream(self, **kwargs):
            result = await self.tools[0].fn(
                question="Quel temps visez-vous ?",
                options=["moins de 3h30", "3h30–4h"],
            )
            self.sessions.tool_results.append(result)
            self.sessions.served[self.id] = True
            yield {
                "type": "AgentEvent",
                "data": {
                    "kind": "answer_event",
                    "answer": f"Le sas choisi par l'utilisateur est {result}.",
                    "outcome": "success",
                },
            }

    class ToolClient:
        def __init__(self):
            self.sessions = FakeSessions()
            self.sessions.tool_results = []

        async def start_session(self, *, tools, **params):
            session = await self.sessions.create_session(**params)
            return ToolSessionHandle(self.sessions, session.id, tools)

    questions = []

    async def ask_user(question: str, options: list[str]) -> str:
        questions.append((question, options))
        return "moins de 3h30"

    @tool(name="ask_user")
    async def ask_user_tool(question: str, options: list[str]) -> str:
        """Request missing details from the runner before continuing."""
        return await ask_user(question, options)

    client = ToolClient()
    runner = HRunner(client, traces_dir=tmp_path, quota_poll_s=0)
    result = asyncio.run(
        runner.run(
            StepKind.registration,
            "Prépare l'inscription",
            tools=[ask_user_tool],
        )
    )
    assert questions == [
        ("Quel temps visez-vous ?", ["moins de 3h30", "3h30–4h"])
    ]
    assert client.sessions.tool_results == ["moins de 3h30"]
    assert "moins de 3h30" in result.summary


def test_every_event_is_traced_without_screenshots(tmp_path):
    runner = make_runner(tmp_path, FakeSessions())
    asyncio.run(runner.run(StepKind.search, "Lis le titre", mission_id="m1"))

    events = TraceWriter("m1", traces_dir=tmp_path).read()
    types = [event.type for event in events]
    assert types[0] == "session_created"
    assert events[0].data["share_url"] == SHARE
    assert events[0].data["h_key"] == "default"
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


@pytest.mark.parametrize(
    "url,allowed_hosts,expected_status,payment_processor",
    [
        ("https://in.njuko.com/race", ("njuko.com",), StepStatus.stopped_before_commitment, False),
        ("https://evil.example/checkout", ("njuko.com",), StepStatus.failed, False),
        ("https://checkout.stripe.com/pay", ("njuko.com",), StepStatus.failed, True),
        ("https://www.booking.com/", ("booking.com",), StepStatus.failed, False),
        ("https://njuko.com.evil.example/", ("njuko.com",), StepStatus.failed, False),
    ],
)
def test_observed_hosts_bound_result_trust(tmp_path, url, allowed_hosts, expected_status, payment_processor):
    events = scripted_events("Stopped before payment; card number required")
    events[1]["data"]["metadata"]["url"] = url
    sessions = FakeSessions(events=events)
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        run = await runner.start(StepKind.registration, "Prepare registration", allowed_hosts=allowed_hosts, mission_id="trust")
        result = await run.wait()
        return run, result

    run, result = asyncio.run(scenario())
    assert result.status is expected_status
    assert run.payment_processor is payment_processor
    assert "allowed_hosts" not in sessions.created[0]
    drift = [event for event in TraceWriter("trust", traces_dir=tmp_path).read() if event.type == "host_drift"]
    if expected_status is StepStatus.failed:
        host = url.split("/")[2]
        assert run.off_platform
        assert result.stop_point is None
        assert result.data["off_platform_hosts"] == [host]
        assert drift[0].data["url"] == url
        assert drift[0].data["allowed"] == list(allowed_hosts)
        assert drift[0].message == f"Agent left {', '.join(allowed_hosts)} for {host}"
        assert result.error == (
            "Payment provider page reached — automation stopped" if payment_processor
            else f"The agent left the official site ({host}); result not trusted"
        )
    else:
        assert not run.off_platform
        assert drift == []


def test_host_drift_remains_untrusted_after_return_to_official_site(tmp_path):
    events = scripted_events("Stopped before payment")
    events.insert(1, {"type": "AgentEvent", "data": {"kind": "observation_event", "metadata": {"url": "https://evil.example/"}}})
    result = asyncio.run(make_runner(tmp_path, FakeSessions(events=events)).run(
        StepKind.registration, "Prepare registration", allowed_hosts=("example.com",),
    ))
    assert result.status is StepStatus.failed
    assert result.data["off_platform_hosts"] == ["evil.example"]
    assert "evil.example" in result.error


@pytest.mark.parametrize("url", ["https://user@evil.tld/", "https://user:password@evil.tld/", "https://@evil.tld/", "javascript:alert(1)", "file:///etc/passwd", "data:text/html,test"])
def test_untrusted_urls_are_not_exposed(url):
    result = build_step_result(StepKind.registration, "completed", last_url=url, live_view_url=url, agent_view_url=url)
    assert result.url is result.live_view_url is result.agent_view_url is None


def test_agent_text_is_sanitized_and_bounded():
    from runai.h.events import answer_text, safe_text

    text = "Ready\x00\x1b\x7f\u200b\u200c\u200d\u2060\ufeff\u202e" + "x" * 2500
    expected = "Ready" + "x" * 1995
    assert safe_text(text) == expected
    assert answer_text(text) == expected
    assert build_step_result(StepKind.registration, "completed", answer=text).summary == expected
    event = {"type": "AgentEvent", "data": {"kind": "policy_event", "content": text}}
    assert event_summary(event) == expected[:200] + "…"


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\t", "\v", "\f"])
def test_control_whitespace_preserves_stop_evidence(separator):
    result = build_step_result(StepKind.registration, "completed", answer=f"Stopped before{separator}payment")
    assert result.status is StepStatus.stopped_before_commitment
    assert result.stop_point is StopPoint.payment
    assert result.summary == "Stopped before" + " " * len(separator) + "payment"


@pytest.mark.parametrize("host", ["stripe.com", "adyen.com", "paypal.com", "checkout.com", "ingenico.com", "worldline.com", "mollie.com"])
def test_payment_provider_is_rejected_even_if_allowlisted(tmp_path, host):
    events = scripted_events("Stopped before payment")
    events[1]["data"]["metadata"]["url"] = f"https://{host}/checkout"
    result = asyncio.run(make_runner(tmp_path, FakeSessions(events=events)).run(
        StepKind.registration, "Prepare registration", allowed_hosts=(host,),
    ))
    assert result.status is StepStatus.failed
    assert result.data["payment_processor"] is True
    assert result.data["off_platform_hosts"] == [host]


def test_run_many_forwards_step_allowed_hosts(tmp_path):
    step = HStep(StepKind.registration, "Prepare registration", allowed_hosts=("njuko.com",))
    result, = asyncio.run(make_runner(tmp_path, FakeSessions()).run_many([step]))
    assert result.status is StepStatus.failed
    assert result.data["off_platform_hosts"] == ["example.com"]


@pytest.mark.parametrize(
    "answer",
    [
        "BLOCAGE CAPTCHA/ANTI-BOT : accès bloqué.",
        "BLOCKED: CAPTCHA/ANTI-BOT at https://example.org/checkout, step 2.",
    ],
)
def test_reported_captcha_block_is_a_failed_step(answer):
    result = build_step_result(StepKind.registration, "completed", answer=answer)
    assert result.status is StepStatus.failed
    assert "captcha" in result.error.lower()


def test_task_anti_bot_marker_is_detected_by_runner():
    from runai.app.tasks import ANTI_BOT_MARKER, STOP_RULES

    assert ANTI_BOT_MARKER in STOP_RULES
    result = build_step_result(
        StepKind.accommodation, "completed", answer=f"{ANTI_BOT_MARKER}: stopped."
    )
    assert result.status is StepStatus.failed


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


@pytest.mark.parametrize("live", [None, LIVE])
def test_live_browser_url_and_durable_agent_view_remain_separate(tmp_path, live):
    sessions = FakeSessions(events=[] if live is None else [{"type": "LiveViewUrlEvent", "data": {"live_view_url": live}}])
    runner = make_runner(tmp_path, sessions)
    result = asyncio.run(runner.run(StepKind.search, "Lis le titre"))
    assert str(result.live_view_url) == (live or SHARE)
    assert str(result.agent_view_url) == VIEW
    assert result.data["share_url"] == SHARE
    assert result.data["h_key"] == "default"


def test_observation_capture_uses_owning_session_resource_not_source_url(tmp_path):
    class Sessions(FakeSessions):
        async def get_session_resource(self, id, bucket, key):
            self.calls.append((id, bucket, key))
            yield b"\x89PNG\r\n\x1a\nimage"

    sessions = Sessions(events=[{"type": "AgentEvent", "data": {"kind": "observation_event",
        "image": {"type": "url", "media_type": "image/png", "source":
                  "https://agp.eu.hcompany.ai/api/v1/trajectories/s1/resources/screens/s1/screenshot-1.png?token=PRIVATE"},
        "metadata": {"url": "https://example.com/", "title": "La page"}}}])

    async def scenario():
        run = await make_runner(tmp_path, sessions).start(StepKind.registration, "Lis la page")
        await run.wait()
        assert run.browser_observation == {"revision": 1, "url": "https://example.com/", "title": "La page"}
        assert await run.get_screenshot() == b"\x89PNG\r\n\x1a\nimage"
        assert sessions.calls[-1] == ("s1", "screens", "s1/screenshot-1.png")
        assert "PRIVATE" not in str(run._result().model_dump())

    asyncio.run(scenario())


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


class RecordingSessions(FakeSessions):
    def __init__(self, *args, network_failures=0, cancel_failures=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_attempts = []
        self.network_failures = network_failures
        self.cancel_failures = cancel_failures

    async def create_session(self, **params):
        self.create_attempts.append(params)
        if self.network_failures:
            self.network_failures -= 1
            raise ConnectionError("network down")
        if self.cancel_failures:
            self.cancel_failures -= 1
            raise asyncio.CancelledError
        return await super().create_session(**params)


@pytest.mark.parametrize("screen,stop", [
    ("payment", StopPoint.payment), ("account", StopPoint.account_creation),
    ("health", StopPoint.health_declaration), ("consent", StopPoint.consent),
    ("submission", StopPoint.submission), ("none", None),
])
def test_typed_answer_precedes_regex(screen, stop):
    result = build_step_result(
        StepKind.registration, "completed",
        answer={"stop_screen": screen, "total_price": 129.0, "final_url": "https://example.org/final"},
        last_url="https://example.org/old",
    )
    assert result.stop_point is stop
    assert result.status is (StepStatus.stopped_before_commitment if stop else StepStatus.completed)
    assert result.price_eur == result.data["price_eur"] == 129.0
    assert str(result.url) == "https://example.org/final"


def test_idempotency_key_is_stable_across_retry_and_increments_per_start(tmp_path):
    sessions = RecordingSessions(create_errors=1)
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        await runner.run(StepKind.search, "x", mission_id="mission")
        await runner.run(StepKind.search, "x", mission_id="mission")
        await runner.run(StepKind.registration, "x", mission_id="mission")
        await runner.run(StepKind.search, "x")
        await runner.run(StepKind.search, "x")
        await runner.run(StepKind.search, "x", mission_id="mission", idempotency_key="caller-key")

    asyncio.run(scenario())
    keys = [p["idempotency_key"] for p in sessions.create_attempts]
    assert keys[:4] == ["mission:search:1", "mission:search:1", "mission:search:2", "mission:registration:1"]
    assert keys[4] != keys[5]
    assert keys[6] == "caller-key"


@pytest.mark.parametrize("failure", ["network_failures", "cancel_failures"])
def test_failed_create_keeps_idempotency_key_for_retry(tmp_path, failure):
    sessions = RecordingSessions(**{failure: 1})
    runner = make_runner(tmp_path, sessions)

    async def scenario():
        with pytest.raises((ConnectionError, asyncio.CancelledError)):
            await runner.start(StepKind.search, "x", mission_id="m")
        await runner.run(StepKind.search, "x", mission_id="m")
        await runner.run(StepKind.search, "x", mission_id="m")

    asyncio.run(scenario())
    assert [p["idempotency_key"] for p in sessions.create_attempts] == ["m:search:1", "m:search:1", "m:search:2"]


@pytest.mark.parametrize("event_type,data", [
    ("AgentRunStatusChangeEvent", {"status": "failed", "error_code": "timeout"}),
    ("AgentErrorEvent", {"error": "failed", "error_code": "timeout"}),
    ("AgentErrorEvent", {"error": "failed", "info": {"error_code": "timeout"}}),
])
def test_event_error_code_and_metrics_are_preserved(tmp_path, event_type, data):
    async def scenario():
        run = await make_runner(tmp_path, FakeSessions()).start(StepKind.search, "x")
        run._absorb({"type": event_type, "data": data})
        run._absorb({"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": 4}}})
        run._absorb({"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": None, "total_cost": 0.2}}})
        assert run.error_code == "timeout"
        assert run.metrics["steps"] == 4 and run.metrics["total_cost"] == 0.2
        await run.close()

    asyncio.run(scenario())


def test_result_reports_elapsed_seconds(tmp_path):
    result = asyncio.run(make_runner(tmp_path, FakeSessions()).run(StepKind.search, "x"))
    assert result.data["elapsed_s"] >= 0


def test_run_many_forwards_mission_id_to_idempotency_keys(tmp_path):
    sessions = RecordingSessions()
    runner = make_runner(tmp_path, sessions)
    asyncio.run(runner.run_many([HStep(StepKind.search, "x"), HStep(StepKind.registration, "y")], mission_id="batch"))
    keys = sorted(p["idempotency_key"] for p in sessions.create_attempts)
    assert keys == ["batch:registration:1", "batch:search:1"]


@pytest.mark.parametrize("copies", [1, 2])
def test_live_metrics_are_deduplicated_and_in_final_result(tmp_path, copies):
    metric = {"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": 2, "total_cost": 0.01}}}
    sessions = FakeSessions(events=[metric] * copies)
    runner = make_runner(tmp_path, sessions)
    seen = []
    result = asyncio.run(runner.run(
        StepKind.search, "Read the title", max_steps=5,
        start_url="https://example.com", mission_id="metrics", on_event=seen.append,
    ))
    metrics = [event for event in TraceWriter("metrics", traces_dir=tmp_path).read() if event.type == "metrics"]
    assert len(metrics) == 1
    assert metrics[0].message == "step 2/5 · $0.010"
    assert metrics[0].data["steps"] == 2
    assert metrics[0].data["total_cost"] == 0.01
    assert metrics[0].data["elapsed_s"] >= 0
    assert [event for event in seen if event["type"] == "metrics"] == [metrics[0].model_dump(mode="json")]
    assert isinstance(result.data["duration_s"], float)
    assert result.data["duration_s"] >= 0
    assert result.data["steps"] == 2
    assert result.data["total_cost"] == 0.01
    assert result.data["h_key"] == "default"
    assert result.data["agent"] == runner.agent
    assert result.data["outcome"] is None
    assert result.data["max_steps"] == 5
    assert result.data["events"] == copies
    assert result.data["start_url"] == "https://example.com"
    assert datetime.fromisoformat(result.data["started_at"]) <= datetime.fromisoformat(result.data["ended_at"])


def test_status_metrics_without_cost_are_deduplicated(tmp_path):
    runner = make_runner(tmp_path, FakeSessions(events=[], final_status="failed"))
    seen = []
    result = asyncio.run(runner.run(StepKind.search, "Read the title", on_event=seen.append))
    metrics = [event for event in seen if event["type"] == "metrics"]
    assert len(metrics) == 1
    assert metrics[0]["data"]["steps"] == 2
    assert metrics[0]["data"]["total_cost"] is None
    assert result.data["total_cost"] is None
    assert result.data["max_steps"] is None
    assert result.data["events"] == 0
    assert result.status is StepStatus.failed


def test_forwarded_metrics_line_keeps_message_and_fields():
    from runai.h.events import to_trace_event

    line = TraceEvent(
        source="h", type="metrics", message="step 2/5 · $0.010",
        data={"h_session_id": "s1", "step": "search", "steps": 2, "total_cost": 0.01, "elapsed_s": 0.1},
    ).model_dump(mode="json")
    event = to_trace_event(line, "s1", "search")
    assert event.type == "metrics"
    assert event.message == "step 2/5 · $0.010"
    assert event.data["steps"] == 2 and event.data["total_cost"] == 0.01
