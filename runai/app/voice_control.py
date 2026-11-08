"""Voice barge-in for a running mission: typed voice commands mapped to H agent controls."""

import asyncio

from pydantic import BaseModel, Field

from runai.app.mission import AGENT_STEPS, MissionError, MissionService
from runai.models import StepKind, StepStatus, TraceEvent
from runai.voice.commands import CommandDetector, command_from_text
from runai.voice.models import (
    CommandEvent,
    CommandKind,
    CommandSource,
    CorrectionTarget,
    TranscriptEvent,
)

PAUSED_PROMPT = 'Agents are paused — say "resume" to continue.'
CANCEL_PROMPT = "Cancelling stops every agent — click \"Cancel mission\" to confirm."
CORRECTION_STEPS = {
    CorrectionTarget.accommodation: StepKind.accommodation,
    CorrectionTarget.transport: StepKind.transport,
    CorrectionTarget.race: StepKind.registration,
}
ACTIVE = {StepStatus.running, StepStatus.paused}


class VoiceControlResult(BaseModel):
    applied: list[str] = Field(default_factory=list)
    pending_confirmation: str | None = None
    ignored_reason: str | None = None
    events: list[CommandEvent] = Field(default_factory=list)


class VoiceMissionController:
    """Mission-scoped: one `CommandDetector` per mission; independent of the transport (HTTP or WebSocket)."""

    def __init__(self, service: MissionService):
        self.service = service
        self._detectors: dict[str, CommandDetector] = {}
        self._finals: dict[str, set[str]] = {}
        self._pause_utterances: dict[str, set[str]] = {}
        self._voice_paused: set[str] = set()
        self._retry_pause: dict[str, set[str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def handle(self, mission_id: str, transcript: TranscriptEvent) -> VoiceControlResult:
        self.service.get(mission_id)
        async with self._locks.setdefault(mission_id, asyncio.Lock()):
            return await self._handle(mission_id, transcript)

    async def _handle(self, mission_id: str, transcript: TranscriptEvent) -> VoiceControlResult:
        result = VoiceControlResult()
        finals = self._finals.setdefault(mission_id, set())
        if transcript.is_final and transcript.utterance_id in finals:
            result.ignored_reason = "Utterance already handled."
            return result
        if transcript.is_final:
            finals.add(transcript.utterance_id)
        events = self._detectors.setdefault(mission_id, CommandDetector()).feed(transcript)
        retry = self._retry_pause.get(mission_id, set())
        if transcript.is_final and transcript.utterance_id in retry:
            retry.discard(transcript.utterance_id)
            early = None if events else command_from_text(transcript.text, CommandSource.voice)
            if early and early.command.kind is CommandKind.pause:
                events = [early.model_copy(update={
                    "utterance_id": transcript.utterance_id, "language": transcript.language,
                })]
        result.events = events
        for event in events:
            await self._dispatch(mission_id, event, result)
        if (
            transcript.is_final
            and result.pending_confirmation is None
            and mission_id in self._voice_paused
            and self._steps_with(mission_id, StepStatus.paused)
        ):
            result.pending_confirmation = PAUSED_PROMPT
        return result

    async def _dispatch(self, mission_id: str, event: CommandEvent, result: VoiceControlResult) -> None:
        kind = event.command.kind
        if kind is CommandKind.pause:
            await self._pause(mission_id, event, result)
        elif kind is CommandKind.resume:
            await self._resume(mission_id, event, result)
        elif kind is CommandKind.correction:
            await self._correct(mission_id, event, result)
        elif kind is CommandKind.cancel:
            result.pending_confirmation = CANCEL_PROMPT
        elif kind is CommandKind.new_mission:
            result.ignored_reason = "A mission is already in progress; voice cannot start a new one."

    async def _pause(self, mission_id: str, event: CommandEvent, result: VoiceControlResult) -> None:
        utterances = self._pause_utterances.setdefault(mission_id, set())
        if event.utterance_id and event.utterance_id in utterances:
            result.ignored_reason = "Pause already requested for this utterance."
            return
        running = self._steps_with(mission_id, StepStatus.running)
        if not running:
            result.ignored_reason = (
                "Agents are already paused." if self._steps_with(mission_id, StepStatus.paused)
                else "No agent is running."
            )
            return
        self._trace(mission_id, "voice.pause_requested", "Voice: pause requested", event, running)
        starting = []
        for kind in running:
            try:
                await self.service.pause(mission_id, kind)
            except MissionError:
                starting.append(kind)
        self._voice_paused.add(mission_id)
        if starting:
            # The final transcript of this utterance retries the pause once those agents have started.
            self._retry_pause.setdefault(mission_id, set()).update({event.utterance_id} - {None})
            result.ignored_reason = "Some agents are still starting: " + ", ".join(k.value for k in starting) + "."
        elif event.utterance_id:
            utterances.add(event.utterance_id)
        if paused := self._steps_with(mission_id, StepStatus.paused):
            result.applied.append("pause")
            self._trace(mission_id, "voice.pause_confirmed", "Voice: agents paused", event, paused)

    async def _resume(self, mission_id: str, event: CommandEvent, result: VoiceControlResult) -> None:
        paused = self._steps_with(mission_id, StepStatus.paused)
        if not paused:
            result.ignored_reason = "No agent is paused."
            return
        await self.service.resume_all(mission_id)
        self._voice_paused.discard(mission_id)
        result.applied.append("resume")
        self._trace(mission_id, "voice.resume", "Voice: agents resumed", event, paused)

    async def _correct(self, mission_id: str, event: CommandEvent, result: VoiceControlResult) -> None:
        target = event.command.target or CorrectionTarget.other
        kind = CORRECTION_STEPS.get(target)
        if kind is None:
            result.ignored_reason = (
                f"Framing is closed: the {target.value} cannot be changed by voice during the mission."
            )
            return
        step = self.service.get(mission_id).steps.get(kind)
        if step is None or step.status not in ACTIVE:
            result.ignored_reason = f"The {kind.value} agent is not running."
            return
        try:
            await self.service.send_message(mission_id, kind, event.command.detail or event.text)
        except MissionError:
            result.ignored_reason = f"The {kind.value} agent cannot receive messages yet; try again shortly."
            return
        result.applied.append(f"correction:{kind.value}")

    def _steps_with(self, mission_id: str, status: StepStatus) -> list[StepKind]:
        steps = self.service.get(mission_id).steps
        return [kind for kind in AGENT_STEPS if kind in steps and steps[kind].status is status]

    def _trace(self, mission_id: str, type_: str, message: str, event: CommandEvent, steps: list[StepKind]) -> None:
        self.service._record(self.service.get(mission_id), TraceEvent(
            source="voice", type=type_, message=message,
            data={
                "steps": [kind.value for kind in steps], "utterance_id": event.utterance_id,
                "text": event.text, "early": event.early,
            },
        ))
