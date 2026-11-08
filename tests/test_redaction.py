import base64
import os

import pytest

from runai.app.replay import ReplayTrace
from runai.contracts.mission import EventEnvelope
from runai.models import StepKind, StepResult
from runai.redaction import redact_secrets


@pytest.mark.parametrize("name", ["HAI_API_KEY", "GLADIA_API_KEY_2", "LINKUP_API_KEY_17"])
def test_nested_payload_masks_configured_variants(monkeypatch, name):
    secret = "provider-secret-123456"
    monkeypatch.setenv(name, secret)
    value = {"nested": [f"error {secret}", (secret, None, 42)], secret: "value"}
    assert redact_secrets(value) == {
        "nested": ["error [REDACTED]", ("[REDACTED]", None, 42)], "[REDACTED]": "value"
    }
    assert value["nested"][0] == f"error {secret}"


def test_empty_short_and_normal_values_unchanged(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "")
    monkeypatch.setenv("GLADIA_API_KEY_2", "Paris")
    value = {"url": "https://example.org/race?city=Paris", "city": "Paris", "empty": ""}
    assert redact_secrets(value) == value
    assert redact_secrets(None) is None


def test_publication_masks_mutated_values(monkeypatch, tmp_path):
    secret = "provider-secret-123456"
    monkeypatch.setenv("LINKUP_API_KEY_2", secret)
    event = EventEnvelope.build("m1", 0, "error", {})
    event.payload["nested"] = [{"message": secret}]
    assert secret not in event.to_sse()
    step = StepResult(kind=StepKind.transport)
    step.error = secret
    assert secret not in step.model_dump_json()
    trace = ReplayTrace(label="trace")
    trace.transcript = secret
    path = tmp_path / "trace.json"
    trace.dump(path)
    assert secret not in path.read_text()


def test_replay_snapshot_masks_raw_events(monkeypatch):
    secret = "provider-secret-123456"
    monkeypatch.setenv("HAI_API_KEY_3", secret)
    trace = ReplayTrace.from_mission_snapshot({
        "id": "m1", "steps": [{"kind": "transport"}],
        "events": [{"source": "h", "type": "error", "message": secret,
                    "data": {"step": "transport"}}],
    })
    assert trace.steps[StepKind.transport].events[0].message == "[REDACTED]"


@pytest.mark.parametrize("name", ["DEVIN_API_KEY", "OPENAI_API_KEY", "RESEND_API_KEY_3"])
def test_any_api_key_variant_is_masked(monkeypatch, name):
    secret = "another-secret-987654"
    monkeypatch.setenv(name, secret)
    assert redact_secrets(f"failed with {secret}") == "failed with [REDACTED]"


def test_basic_auth_credentials_masked(monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "user:pass")
    value = redact_secrets({"h": "Basic dXNlcjpwYXNz", "a": os.environ["RUNAI_BASIC_AUTH"]})
    assert value == {"h": "Basic [REDACTED]", "a": "[REDACTED]"}


def test_basic_auth_password_part_masked(monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "demo:long-password-42")
    assert redact_secrets("pw=long-password-42") == "pw=[REDACTED]"
    assert redact_secrets("demo:long-password-42") == "[REDACTED]"


def test_short_basic_auth_password_and_pair_masked(monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "u:pw")
    assert redact_secrets("u:pw pw") == "[REDACTED] [REDACTED]"


def test_multiple_basic_auth_passwords_and_encoded_pairs_masked(monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "alice:Pass1,bob:Pass2")
    for pair in ("alice:Pass1", "bob:Pass2"):
        password = pair.partition(":")[2]
        encoded = base64.b64encode(pair.encode()).decode()
        assert redact_secrets(f"failure {password} {encoded}") == "failure [REDACTED] [REDACTED]"
    assert redact_secrets("alice:Pass1,bob:Pass2") == "[REDACTED]"


@pytest.mark.parametrize("text,expected", [
    ("hk" + "-abcdefghijklmnop_123", "[REDACTED]"),
    ("https://alice:fake-password@example.org/path", "https://[REDACTED]@example.org/path"),
    ("https://example.org/?token=fake&city=Paris", "https://example.org/?token=[REDACTED]&city=Paris"),
    ("?access_token=fake&api_key=fake&key=fake&secret=fake#top",
     "?access_token=[REDACTED]&api_key=[REDACTED]&key=[REDACTED]&secret=[REDACTED]#top"),
])
def test_unconfigured_credential_patterns_are_masked(text, expected):
    assert redact_secrets(text) == expected


def test_authorization_header_values_masked(monkeypatch):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    value = {
        "headers": {"Authorization": "Bearer abcdefghijklmnop", "Proxy-Authorization": "token xyz",
                    "Accept": "application/json"},
        "log": "sent Authorization: Bearer abcdefghijklmnop",
    }
    assert redact_secrets(value) == {
        "headers": {"Authorization": "[REDACTED]", "Proxy-Authorization": "[REDACTED]",
                    "Accept": "application/json"},
        "log": "sent Authorization: Bearer [REDACTED]",
    }
    assert redact_secrets("Bearer short") == "Bearer short"
    assert redact_secrets("bearer abcdefgh12345678") == "bearer [REDACTED]"
    assert redact_secrets("BASIC dXNlcjpwYXNz") == "BASIC [REDACTED]"


def test_plain_text_after_auth_scheme_words_kept(monkeypatch):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    text = "Basic training plan, bearer of the race bib"
    assert redact_secrets(text) == text


def test_short_bearer_and_non_utf8_basic_masked(monkeypatch):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    token = base64.b64encode(b"user:\xff\xfepass").decode()
    assert redact_secrets("Bearer abcd1234") == "Bearer [REDACTED]"
    assert redact_secrets(f"Basic {token}") == "Basic [REDACTED]"


def test_bearer_prose_is_preserved():
    text = "The bearer presents identification."
    assert redact_secrets(text) == text
