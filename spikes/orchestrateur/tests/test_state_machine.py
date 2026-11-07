import asyncio

import pytest
from runai_orch.contracts import MissionKind
from runai_orch.contracts import MissionState as S
from runai_orch.orchestrator import check_answer
from runai_orch.state import InvalidTransition, Mission, can_transition

from tests.helpers import trip


def test_transitions_table():
    assert can_transition(S.queued, S.running)
    assert can_transition(S.running, S.waiting_human)
    assert can_transition(S.waiting_human, S.ready_to_pay)
    assert can_transition(S.ready_to_pay, S.running)  # correction apres le recap
    assert not can_transition(S.queued, S.ready_to_pay)
    assert not can_transition(S.failed, S.running)
    assert not can_transition(S.cancelled, S.running)


def test_transition_emits_events_and_rejects_invalid():
    async def go():
        m = Mission(id="m", trip_id="t", kind=MissionKind.hotel, task="x")
        await m.transition(S.running)
        await m.transition(S.waiting_human, "paused_by_user")
        assert m.waiting_reason == "paused_by_user"
        assert not await m.transition(S.waiting_human, "paused_by_user")  # no-op
        await m.transition(S.cancelled, "cancelled_by_user")
        with pytest.raises(InvalidTransition):
            await m.transition(S.running)
        assert [e.data["to"] for e in m.events] == ["running", "waiting_human", "cancelled"]
        assert [e.seq for e in m.events] == [0, 1, 2]
    asyncio.run(go())


def test_stream_replays_then_ends_on_terminal():
    async def go():
        m = Mission(id="m", trip_id="t", kind=MissionKind.hotel, task="x")
        await m.transition(S.running)
        got = []

        async def reader():
            async for ev in m.stream(0, keepalive_s=0.05):
                if ev is not None:
                    got.append(ev.type)
        r = asyncio.create_task(reader())
        await asyncio.sleep(0.02)
        await m.emit("step", {"thought": "x"})
        await m.transition(S.failed, "boom")
        await asyncio.wait_for(r, 1)
        assert got == ["state", "step", "state"]
    asyncio.run(go())


BASE = {"ready_for_payment": True, "payment_submitted": False, "blocked": False}


@pytest.mark.parametrize("answer,state,reason", [
    ({**BASE, "total_price_eur": 8, "distance_km": 10}, S.ready_to_pay, None),
    ({**BASE, "payment_submitted": True}, S.failed, "payment_submitted"),
    ({**BASE, "blocked": True}, S.waiting_human, "blocked"),
    ({**BASE, "total_price_eur": 500}, S.waiting_human, "over_budget"),
    ({**BASE, "distance_km": 21.1}, S.waiting_human, "wrong_distance"),
    ({**BASE, "ready_for_payment": False}, S.waiting_human, "incomplete"),
    ({"foo": 1}, S.failed, None),
    ("not json", S.failed, "answer_not_json"),
])
def test_check_answer_server_side_filter(answer, state, reason):
    got_state, got_reason, _ = check_answer(MissionKind.inscription, answer, trip(max_budget_eur=300))
    assert got_state == state
    if reason:
        assert got_reason == reason


def test_answer_formats_are_json_schemas():
    from runai_orch.contracts import answer_format
    for k in MissionKind:
        s = answer_format(k)
        assert s["type"] == "object"
        assert {"ready_for_payment", "payment_submitted", "blocked"} <= set(s["required"])
