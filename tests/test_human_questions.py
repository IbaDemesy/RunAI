import asyncio
from datetime import timedelta

import pytest

from runai.contracts.mission import HumanAnswer, QuestionStatus
from runai.h.human_questions import HumanQuestionError, HumanQuestionRegistry
from runai.models import AgentQuestion, StepKind, utcnow


def open_question(registry, text="Quelle option ?", **kwargs):
    return registry.open(
        AgentQuestion(
            id="q1", kind=StepKind.registration, question=text, options=["A", "B"]
        ),
        "m1",
        3,
        "h-session",
        **kwargs,
    )


def answer(**kwargs):
    return HumanAnswer(answer="oui", revision=3, idempotency_key="answer-key", **kwargs)


def test_correlation_and_idempotency():
    registry = HumanQuestionRegistry()
    question = open_question(registry)
    assert question.session_id == "h-session"
    with pytest.raises(HumanQuestionError):
        registry.answer("q1", "wrong", answer())
    with pytest.raises(HumanQuestionError):
        registry.answer("q1", "m1", answer().model_copy(update={"revision": 2}))
    result = registry.answer("q1", "m1", answer())
    assert result.status == QuestionStatus.answered
    assert registry.answer("q1", "m1", answer()) == result
    with pytest.raises(HumanQuestionError):
        registry.answer(
            "q1", "m1", answer().model_copy(update={"idempotency_key": "other-key"})
        )
    assert registry.to_agent_question("q1").answer == "oui"
    assert asyncio.run(registry.wait_answer("q1", 1)) == "oui"


@pytest.mark.parametrize(
    "text",
    [
        "Effectuer le paiement ?",
        "Créer un compte ?",
        "Déclaration de santé ?",
        "Accepter le consentement ?",
        "Soumettre ?",
        "Envoyer le formulaire ?",
        "Réserver ?",
    ],
)
def test_yes_never_authorizes_commitment(text):
    registry = HumanQuestionRegistry()
    open_question(registry, text)
    result = registry.answer("q1", "m1", answer())
    assert result.status == QuestionStatus.refused
    assert "Aucune autorisation" in result.reason
    assert registry.to_agent_question("q1").answer is None
    with pytest.raises(HumanQuestionError):
        asyncio.run(registry.wait_answer("q1", 1))


def test_expired_cancelled_and_wait():
    registry = HumanQuestionRegistry()
    open_question(registry, expires_at=utcnow() - timedelta(seconds=1))
    with pytest.raises(HumanQuestionError, match="expirée"):
        registry.answer("q1", "m1", answer())
    registry = HumanQuestionRegistry()
    open_question(registry)
    registry.cancel_mission("m1")
    with pytest.raises(HumanQuestionError, match="cancelled"):
        registry.answer("q1", "m1", answer())

    async def run():
        registry = HumanQuestionRegistry()
        open_question(registry)
        task = asyncio.create_task(registry.wait_answer("q1", 1))
        await asyncio.sleep(0)
        registry.answer("q1", "m1", answer())
        assert await task == "oui"
        other = HumanQuestionRegistry()
        open_question(other)
        with pytest.raises(HumanQuestionError, match="expirée"):
            await other.wait_answer("q1", 0.001)
        assert other.get("q1").status == QuestionStatus.expired

    asyncio.run(run())


def test_engaging_choice_is_never_authorized_by_generic_question():
    registry = HumanQuestionRegistry()
    registry.open(
        AgentQuestion(
            id="q1",
            kind=StepKind.registration,
            question="Continuer ?",
            options=["Paiement", "Annuler"],
        ),
        "m1",
        3,
    )
    assert registry.answer("q1", "m1", answer()).status == QuestionStatus.refused
