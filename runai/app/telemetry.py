"""Read-only provider telemetry endpoints."""

from fastapi import APIRouter, Query

from runai import telemetry
from runai.redaction import redact_secrets
from runai.telemetry import Provider

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.get("/calls")
def calls(correlation_id: str | None = None, provider: Provider | None = None,
          limit: int | None = Query(default=None, ge=0)):
    return redact_secrets([call.model_dump(mode="json") for call in
                           telemetry.default_log.list(correlation_id, provider, limit)])


@router.get("/summary")
def summary():
    return redact_secrets(telemetry.default_log.summary())
