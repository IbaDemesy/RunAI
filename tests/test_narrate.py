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
            "Sur example.com · Course officielle",
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
            "Sur example.com",
        ),
        (
            TraceEvent(source="app", type="step_started"),
            "Ouverture du navigateur…",
        ),
        (
            TraceEvent(
                source="agent:registration",
                type="question",
                message="Quel sas souhaitez-vous ?",
            ),
            "Attend votre réponse : Quel sas souhaitez-vous ?",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentErrorEvent",
                message="captcha",
            ),
            "Site protégé par un captcha : l'agent s'est arrêté. Finissez cette étape vous-même sur le site officiel.",
        ),
        (
            TraceEvent(
                source="h",
                type="AgentEvent.error_event",
                message="403 Forbidden",
            ),
            "Le service d'agents est indisponible pour le moment.",
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
            TraceEvent(source="agent:registration", type="answer", message="Découverte"),
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

    assert headline(event) == f"Sur race.example · {title[:80]}…"
    assert len(headline(event)) <= 120


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "ANTI-BOT BLOCAGE",
            "Site protégé par un captcha : l'agent s'est arrêté. Finissez cette étape vous-même sur le site officiel.",
        ),
        (
            "The operation TIMED OUT",
            "Le site a mis trop de temps à répondre. Vous pouvez reprendre cette étape vous-même.",
        ),
        (
            "API KEY rejected: 401",
            "Le service d'agents est indisponible pour le moment.",
        ),
        (
            "HORS BUDGET : 401 € dépasse 403 euros pour 2 nuits.",
            "HORS BUDGET : 401 € dépasse 403 euros pour 2 nuits.",
        ),
        (
            "Hébergement non automatisé : aucun site officiel autorisé.",
            "Hébergement non automatisé : aucun site officiel autorisé.",
        ),
        (
            "Traceback (most recent call last):\nRuntimeError: failed",
            "L'agent n'a pas pu terminer cette étape. Vous pouvez la faire vous-même depuis le site officiel.",
        ),
    ],
)
def test_friendly_error(text, expected):
    assert friendly_error(text) == expected
