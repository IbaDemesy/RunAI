import json
from pathlib import Path

import pytest

from runai.h.events import compact, to_trace_event
from runai.tracing import TraceWriter
from scripts.scrub_trace import find_violations, main, scrub_event


def test_trace_writer_masks_h_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "hk-test-secret-123456")
    writer = TraceWriter("safe", tmp_path)
    writer.write(to_trace_event({"type": "AgentEvent", "data": {"token": "hk-test-secret-123456"}}, "s1", "test"))
    assert "hk-test-secret-123456" not in writer.path.read_text()
    assert "[REDACTED]" in writer.path.read_text()
    assert writer.read()[0].data["event"]["data"]["token"] == "[REDACTED]"


def test_compact_sensitive_fields():
    payload = {key: "secret" for key in ("cookies", "Headers", "authorization", "set-cookie", "password")}
    payload["reasoning_content"] = "x" * 600
    assert compact({"nested": [payload]}) == {"nested": [{"reasoning_content": "x" * 300}]}
    assert compact({}) == {}
    assert compact({"reasoning_content": None}) == {"reasoning_content": None}


def test_scrub_main(tmp_path, capsys):
    source = tmp_path / "source.jsonl"
    output = tmp_path / "public.jsonl"
    source.write_text(json.dumps({
        "token": "hk-test-secret-123456", "email": "person@private.org",
        "profile": "camille.test@example.com", "phone": "+33612345678",
        "agent_view_url": "https://private.example.com", "nested": [{"live_view_url": "secret"}],
        "resource": "https://api.hcompany.ai/api/v1/trajectories/secret",
        "share_url": "https://example.com/share/public",
    }) + "\n")
    main([str(source), str(output)])
    clean = json.loads(output.read_text())
    assert find_violations(clean) == []
    assert "hk-" not in output.read_text()
    assert "agent_view_url" not in output.read_text()
    assert clean["share_url"] == "https://example.com/share/public"
    assert clean["profile"] == "runner@example.com"
    assert clean["phone"] == "+33000000000"
    assert "Events kept: 1; fields scrubbed:" in capsys.readouterr().out


def test_scrub_empty_and_invalid(tmp_path):
    source, output = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    source.write_text("")
    main([str(source), str(output)])
    assert output.read_text() == ""
    assert scrub_event({}) == {}
    source.write_text("not JSON")
    with pytest.raises(json.JSONDecodeError):
        main([str(source), str(output)])
    assert output.read_text() == ""


@pytest.mark.parametrize("value", [
    {"agent_view_url": "x"}, {"nested": [{"live_view_url": "x"}]},
    "hk-unknown-key", "person@private.org", "https://h.example.com/api/v1/trajectories/id",
])
def test_checker_detects_violations(value):
    assert find_violations(value)
    assert find_violations(scrub_event(value)) == []


def test_repository_fixture_hygiene():
    root = Path(__file__).resolve().parents[1]
    failures = []
    for directory in ("tests/fixtures", "runai/contracts/fixtures", "fixtures"):
        for path in (root / directory).rglob("*"):
            if path.suffix not in {".json", ".jsonl"}:
                continue
            documents = path.read_text().splitlines() if path.suffix == ".jsonl" else [path.read_text()]
            for document in documents:
                if not document.strip():
                    continue
                try:
                    payload = json.loads(document)
                except json.JSONDecodeError:
                    continue  # Malformed-on-purpose robustness fixtures.
                failures.extend(f"{path.relative_to(root)}: {issue}" for issue in find_violations(payload))
    assert not failures, "\n".join(failures)


def test_scrub_keeps_message_and_null_phone():
    from scripts.scrub_trace import scrub_event

    event = {
        "message": "Opened https://agp.hcompany.ai/api/v1/trajectories/abc then call +33 6 12 34 56 78",
        "phone": None,
    }
    clean = scrub_event(event)
    assert clean["phone"] is None
    assert clean["message"].startswith("Opened [REDACTED] then call")
    assert "12 34 56" not in clean["message"]
