import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingError,
    FramingReply,
    RaceCandidate,
    SlotName,
)
from runai.contracts.mission import MissionSnapshot
from runai.framing.engine import FramingEngine
from runai.h.lifecycle import HAntiBotBlocked, HJobCancelled, HLifecycle, JobState
from runai.models import Source, StepKind, StepResult, StepStatus


class Search:
    async def find_candidates(self, slots, request_text: str | None = None):
        return [
            RaceCandidate(
                id="c1",
                name="Course sourcée",
                city=slots[SlotName.city].value,
                country="JP",
                race_date=date(2028, 6, 12),
                distances_km=[10],
                sources=[Source(url="https://example.org/race")],
                provenance=Provenance(kind="fixture", url="https://example.org/race"),
            )
        ]


@pytest.mark.parametrize("city", ["Tokyo", "Nairobi", "Lisbonne"])
@pytest.mark.parametrize("channel", ["text", "voice"])
def test_confirmation_once_and_cancelled_or_stale_never_launch(city, channel):
    async def scenario():
        engine = FramingEngine(Search(), DataMode.demo)
        launches = []

        async def launch(session):
            launches.append(session.id)
            await asyncio.sleep(0)
            return MissionSnapshot(
                mission_id="m1",
                framing_id=session.id,
                framing_revision=session.revision,
                mode=session.mode,
                status="running",
                sequence=0,
                steps=[],
            )

        session = await engine.create(
            FramingCreate(
                text=(
                    f"Une course à {city}, 10 km en juin 2028, depuis Lyon, "
                    "800 euros, 2 nuits, en avion"
                ),
                channel=channel,
            )
        )
        session = await engine.reply(
            session.id,
            FramingReply(revision=session.revision, choice_id="c1", channel=channel),
        )
        old_revision = session.revision
        session = await engine.reply(
            session.id,
            FramingReply(
                revision=old_revision, text="budget 900 euros", channel=channel
            ),
        )
        with pytest.raises(FramingError):
            await engine.confirm(
                session.id,
                FramingConfirm(revision=old_revision, idempotency_key="confirm-1"),
                launch,
            )
        assert not launches
        request = FramingConfirm(revision=session.revision, idempotency_key="confirm-1")
        a, b = await asyncio.gather(
            engine.confirm(session.id, request, launch),
            engine.confirm(session.id, request, launch),
        )
        assert a == b and launches == [session.id]
        other = await engine.create(FramingCreate(text=f"Une course à {city}"))
        await engine.cancel(other.id)
        with pytest.raises(FramingError):
            await engine.confirm(
                other.id,
                FramingConfirm(revision=other.revision, idempotency_key="confirm-2"),
                launch,
            )
        assert launches == [session.id]

    asyncio.run(scenario())


def test_captcha_fails_without_retry_or_resume():
    async def scenario():
        run = SimpleNamespace(
            status="completed",
            close=AsyncMock(),
            resume=AsyncMock(),
            wait=AsyncMock(
                return_value=StepResult(
                    kind=StepKind.registration,
                    status=StepStatus.failed,
                    error="BLOCAGE CAPTCHA/ANTI-BOT",
                )
            ),
        )
        runner = SimpleNamespace(start=AsyncMock(return_value=run), accounts=[])
        lifecycle = HLifecycle(runner)
        job = lifecycle.submit(StepKind.registration, "t", mission_id="m1")
        with pytest.raises(HAntiBotBlocked, match="not bypassed"):
            await job.wait()
        assert job.state is JobState.failed
        runner.start.assert_awaited_once()
        run.resume.assert_not_called()
        run.close.assert_awaited_once()

    asyncio.run(scenario())


def test_cancel_mission_does_not_cancel_other_queued_mission():
    async def scenario():
        runner = SimpleNamespace(start=AsyncMock(), accounts=[])
        lifecycle = HLifecycle(runner)
        await lifecycle.pause_all()
        a = lifecycle.submit(StepKind.registration, "t", mission_id="m1")
        b = lifecycle.submit(StepKind.transport, "t", mission_id="m2")
        await asyncio.sleep(0)
        await lifecycle.cancel_all("m1")
        with pytest.raises(HJobCancelled):
            await a.wait()
        assert b.state is JobState.queued and not b.done
        runner.start.assert_not_called()
        await lifecycle.cancel_all("m2")

    asyncio.run(scenario())


def test_cancel_running_mission_leaves_other_running_mission_untouched():
    async def scenario():
        started = {mission: asyncio.Event() for mission in ("m1", "m2")}
        finish = {mission: asyncio.Event() for mission in started}
        runs = {}
        for mission, event in started.items():
            async def wait(*, timeout_s=None, mission=mission, event=event):
                event.set()
                await finish[mission].wait()
                return StepResult(kind=StepKind.transport, status=StepStatus.completed)

            runs[mission] = SimpleNamespace(
                status="running",
                wait=wait,
                close=AsyncMock(),
                pause=AsyncMock(),
                resume=AsyncMock(),
            )

        async def start(kind, task, *, mission_id):
            return runs[mission_id]

        runner = SimpleNamespace(start=AsyncMock(side_effect=start), accounts=[])
        lifecycle = HLifecycle(runner)
        a = lifecycle.submit(StepKind.transport, "t", mission_id="m1")
        b = lifecycle.submit(StepKind.transport, "t", mission_id="m2")
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started.values())), 1
            )
            assert a.state is b.state is JobState.running
            await lifecycle.cancel_all("m1")
            await lifecycle.cancel_all("m1")
            with pytest.raises(HJobCancelled):
                await a.wait()
            assert b.state is JobState.running and not b.done
            runs["m1"].close.assert_awaited_once()
            for action in ("close", "pause", "resume"):
                getattr(runs["m2"], action).assert_not_called()
            finish["m2"].set()
            assert (await asyncio.wait_for(b.wait(), 1)).status is StepStatus.completed
            assert b.state is JobState.completed
            runs["m2"].close.assert_awaited_once()
            assert runner.start.await_count == 2
        finally:
            await lifecycle.cancel_all()

    asyncio.run(scenario())
