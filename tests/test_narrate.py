import pytest

from runai.h.narrate import friendly_error, headline
from runai.models import TraceEvent


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            TraceEvent(
                source="h",
                type="AgentEvent.observation_event",
                data={
                    "event": {
                        "type": "AgentEvent",
                        "data": {
                            "kind": "observation_event",
                            "metadata": {
                                "url": "https://www.example.com/results",
                                "title": "Course officielle",
                            },
                        },
                    }
                },
            ),
            "On example.com · Course officielle",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentEvent.observation_event",
                data={
                    "event": {
                        "data": {
                            "kind": "observation_event",
                            "metadata": {"url": "https://www.example.com/results"},
                        }
                    }
                },
            ),
            "On example.com",
        ),
        (
            TraceEvent(source="app", type="step_started"),
            "Opening the browser…",
        ),
        (
            TraceEvent(
                source="agent:registration",
                type="question",
                message="Quel sas souhaitez-vous ?",
            ),
            "Waiting for your answer: Quel sas souhaitez-vous ?",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentErrorEvent",
                message="captcha",
            ),
            "The site is protected by a captcha: the agent stopped. Finish this step yourself on the official site.",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentEvent.error_event",
                message="403 Forbidden",
            ),
            "The agent service is currently unavailable.",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentEvent.policy_event",
                message="I will open the browser",
            ),
            None,
        ),
        (
            TraceEvent(source="h", type="LiveViewUrlEvent", message="vue live disponible"),
            None,
        ),
        (
            TraceEvent(source="agent:registration", type="answer", message="Discovery"),
            None,
        ),
    ],
)
def test_headline_for_trace_event(event, expected):
    assert headline(event) == expected


def test_observation_headline_truncates_long_title():
    title = "Course " + "officielle " * 12
    event = TraceEvent(
        source="h",
        type="AgentEvent.observation_event",
        data={
            "event": {
                "data": {
                    "kind": "observation_event",
                    "metadata": {"url": "https://race.example/page", "title": title},
                }
            }
        },
    )

    assert headline(event) == f"On race.example · {title[:80]}…"
    assert len(headline(event)) <= 120


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "ANTI-BOT BLOCAGE",
            "The site is protected by a captcha: the agent stopped. Finish this step yourself on the official site.",
        ),
        (
            "The operation TIMED OUT",
            "The site took too long to respond. You can complete this step yourself.",
        ),
        (
            "API KEY rejected: 401",
            "The agent service is currently unavailable.",
        ),
        (
            "OVER BUDGET: 401 € exceeds 403 euros pour 2 nuits.",
            "OVER BUDGET: 401 € exceeds 403 euros pour 2 nuits.",
        ),
        (
            "Hébergement non automatisé : aucun site officiel autorisé.",
            "Hébergement non automatisé : aucun site officiel autorisé.",
        ),
        (
            "Traceback (most recent call last):\nRuntimeError: failed",
            "The agent could not finish this step. You can complete it yourself on the official site.",
        ),
    ],
)
def test_friendly_error(text, expected):
    assert friendly_error(text) == expected
