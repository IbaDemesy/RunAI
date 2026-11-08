"""HTTP entry point for voice barge-in during a mission (a WebSocket can reuse the same controller)."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from runai.app.mission import MissionError
from runai.app.voice_control import VoiceMissionController
from runai.redaction import redact_secrets
from runai.voice.models import TranscriptEvent

router = APIRouter()


class VoiceTranscriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    is_final: bool
    utterance_id: str = Field(min_length=1, max_length=100)
    language: str | None = Field(default=None, max_length=16)


def voice_controller(request: Request) -> VoiceMissionController:
    service = request.app.state.service
    controller = getattr(request.app.state, "voice_controller", None)
    if controller is None or controller.service is not service:
        controller = VoiceMissionController(service)
        request.app.state.voice_controller = controller
    return controller


@router.post("/api/missions/{mission_id}/voice")
async def mission_voice(mission_id: str, body: VoiceTranscriptRequest, request: Request) -> dict:
    transcript = TranscriptEvent(
        text=body.text, is_final=body.is_final, utterance_id=body.utterance_id, language=body.language,
    )
    try:
        result = await voice_controller(request).handle(mission_id, transcript)
    except MissionError as error:
        status = 404 if "inconnue" in str(error) or "unknown" in str(error).lower() else 409
        raise HTTPException(status_code=status, detail=redact_secrets(str(error))) from None
    return result.model_dump(mode="json")
