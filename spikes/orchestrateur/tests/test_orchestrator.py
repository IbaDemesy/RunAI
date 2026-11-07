import asyncio

from runai_orch.adapters.base import AdapterEvent as E
from runai_orch.adapters.mock import MockHAdapter
from runai_orch.contracts import MissionState as S
from runai_orch.orchestrator import Orchestrator

from tests.helpers import trip, wait_state


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def test_three_missions_in_parallel_reach_expected_states():
    async def go():
        o = Orchestrator(MockHAdapter(speed=100), poll_s=0.01)
        _, ms = await o.create_trip(trip())
        ins, hotel, transport = ms
        await wait_state(hotel, S.ready_to_pay)
        await wait_state(transport, S.ready_to_pay)
        await wait_state(ins, S.waiting_human)
        assert ins.waiting_reason == "consent"
        await o.message(ins.id, "Je coche moi-meme, continue")
        await wait_state(ins, S.ready_to_pay)
        assert ("tool_result", ins.session_id) in o.adapter.calls
        assert ins.answer["platform"] == "Njuko" and ins.live_view_url.endswith(ins.session_id)
        starts = [c for c in o.adapter.calls if c[0] == "start"]
        assert len(starts) == 3
        await o.shutdown()
        assert all(m.state == S.cancelled for m in ms)
        assert sum(1 for c in o.adapter.calls if c[0] == "cancel") == 3
        assert (await o.adapter.quota()).available == 3
    run(go())


def test_pause_resume_and_correction_message():
    async def go():
        slow = [(0.0, E("status", {"h_status": "running"}))] + [(0.05, E("step", {"thought": f"s{i}"})) for i in range(40)]
        o = Orchestrator(MockHAdapter(speed=1, scripts={"hotel": slow}), poll_s=0.01)
        _, ms = await o.create_trip(trip(kinds=["hotel"]))
        h = ms[0]
        await wait_state(h, S.running)
        await o.pause(h.id)
        assert h.state == S.waiting_human and h.waiting_reason == "paused_by_user"
        steps = h.steps
        await asyncio.sleep(0.2)
        assert h.steps <= steps + 1  # au plus l'evenement deja en vol
        await o.resume(h.id)
        assert h.state == S.running
        await o.message(h.id, "Prends plutot un hotel avec annulation gratuite")
        assert ("message", h.session_id) in o.adapter.calls
        await o.cancel(h.id)
        assert h.state == S.cancelled
    run(go())


def test_queue_when_three_slots_taken_then_starts_after_cancel():
    async def go():
        o = Orchestrator(MockHAdapter(speed=100), poll_s=0.01)
        _, first = await o.create_trip(trip())
        for m in first[1:]:
            await wait_state(m, S.ready_to_pay)  # idle : garde son slot, comme H
        _, second = await o.create_trip(trip(kinds=["hotel"]))
        h2 = second[0]
        await asyncio.sleep(0.1)
        assert h2.state == S.queued and o.public(h2).queue_position == 0
        await o.cancel(first[1].id)
        await wait_state(h2, S.ready_to_pay)
        await o.shutdown()
    run(go())


def test_external_org_usage_blocks_then_times_out():
    async def go():
        o = Orchestrator(MockHAdapter(speed=100, external_active=3), poll_s=0.02, max_wait_s=0.1)
        _, ms = await o.create_trip(trip(kinds=["transport"]))
        await wait_state(ms[0], S.failed)
        assert ms[0].error.startswith("h_quota_timeout")
        assert not [c for c in o.adapter.calls if c[0] == "start"]
    run(go())


def test_cancel_while_queued_removes_from_queue():
    async def go():
        o = Orchestrator(MockHAdapter(speed=100, external_active=3), poll_s=0.02, max_wait_s=30)
        _, ms = await o.create_trip(trip(kinds=["hotel"]))
        await asyncio.sleep(0.05)
        assert o.scheduler.queue
        await o.cancel(ms[0].id)
        assert ms[0].state == S.cancelled and not o.scheduler.queue
    run(go())


def test_payment_submitted_fails_and_cancels_session():
    async def go():
        bad = {"ready_for_payment": True, "payment_submitted": True, "blocked": False}
        script = [(0.0, E("status", {"h_status": "running"})), (0.01, E("answer", {"answer": bad})),
                  (0.0, E("status", {"h_status": "idle"}))]
        o = Orchestrator(MockHAdapter(speed=100, scripts={"hotel": script}), poll_s=0.01)
        _, ms = await o.create_trip(trip(kinds=["hotel"]))
        await wait_state(ms[0], S.failed)
        assert ms[0].error == "payment_submitted"
        assert ("cancel", ms[0].session_id) in o.adapter.calls
    run(go())


def test_adapter_crash_fails_mission_and_releases_slot():
    class Boom(MockHAdapter):
        async def start(self, spec):
            raise RuntimeError("network")

    async def go():
        o = Orchestrator(Boom(speed=100), poll_s=0.01)
        _, ms = await o.create_trip(trip(kinds=["hotel"]))
        await wait_state(ms[0], S.failed)
        await asyncio.sleep(0.01)
        assert ms[0].error == "RuntimeError" and not o.scheduler.held
    run(go())
