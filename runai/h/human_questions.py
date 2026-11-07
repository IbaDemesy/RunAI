import asyncio
import re
from datetime import datetime, timedelta

from runai.contracts.mission import HumanAnswer, HumanQuestion, QuestionStatus
from runai.models import AgentQuestion, utcnow
from runai.safety import detect_stop_point


class HumanQuestionError(Exception):
    """Réponse non corrélée, périmée ou non autorisée."""


class HumanQuestionRegistry:
    def __init__(self):
        self.questions: dict[str, HumanQuestion] = {}
        self._keys: dict[str, str] = {}
        self._events: dict[str, asyncio.Event] = {}

    def open(
        self,
        question: AgentQuestion,
        mission_id: str,
        revision: int,
        session_id: str | None = None,
        *,
        expires_at: datetime | None = None,
        ttl: float = 300,
    ) -> HumanQuestion:
        if question.id in self.questions:
            raise HumanQuestionError("Identifiant de question déjà utilisé")
        if question.answer is not None:
            raise HumanQuestionError("Question déjà répondue")
        wrapped = HumanQuestion.from_agent_question(
            question,
            mission_id,
            revision,
            session_id,
            expires_at or utcnow() + timedelta(seconds=ttl),
        )
        self.questions[question.id] = wrapped
        self._events[question.id] = asyncio.Event()
        return wrapped.model_copy(deep=True)

    def get(self, question_id: str) -> HumanQuestion:
        try:
            return self.questions[question_id].model_copy(deep=True)
        except KeyError as exc:
            raise HumanQuestionError("Question inconnue") from exc

    def answer(
        self,
        question_id: str,
        mission_id: str,
        answer: HumanAnswer,
        now: datetime | None = None,
    ) -> HumanQuestion:
        self.get(question_id)
        question = self.questions[question_id]
        if question.mission_id != mission_id or question.revision != answer.revision:
            raise HumanQuestionError("Mission ou révision incorrecte")
        if question.status in (QuestionStatus.answered, QuestionStatus.refused):
            if (
                self._keys.get(question_id) == answer.idempotency_key
                and question.answer == answer.answer
            ):
                return self.get(question_id)
            raise HumanQuestionError("Question déjà répondue")
        if question.status != QuestionStatus.open:
            raise HumanQuestionError(f"Question {question.status.value}")
        if question.expires_at and (now or utcnow()) >= question.expires_at:
            question.status = QuestionStatus.expired
            self._events[question_id].set()
            raise HumanQuestionError("Question expirée")
        question.answer = answer.answer
        text = f"{question.text} {' '.join(question.choices)} {question.reason or ''} {answer.answer}"
        stop = detect_stop_point(text)
        forbidden = stop is not None or re.search(
            r"\b(compte|account|santé|health|consentement|consent|envoi|envoyer|send|soumission|réservation|booking)\b",
            text,
            re.IGNORECASE,
        )
        question.status = (
            QuestionStatus.refused if forbidden else QuestionStatus.answered
        )
        if forbidden:
            question.reason = f"Arrêt humain obligatoire : {stop.value if stop else 'engagement interdit'}. Aucune autorisation d'automatisation."
        self._keys[question_id] = answer.idempotency_key
        self._events[question_id].set()
        return self.get(question_id)

    def cancel(self, question_id: str) -> HumanQuestion:
        self.get(question_id)
        question = self.questions[question_id]
        if question.status == QuestionStatus.open:
            question.status = QuestionStatus.cancelled
            self._events[question_id].set()
        return self.get(question_id)

    def cancel_mission(self, mission_id: str) -> None:
        for qid, question in self.questions.items():
            if question.mission_id == mission_id:
                self.cancel(qid)

    async def wait_answer(self, question_id: str, timeout: float | None = None) -> str:
        question = self.get(question_id)
        remaining = (
            max(0, (question.expires_at - utcnow()).total_seconds())
            if question.expires_at
            else None
        )
        wait = (
            min(timeout, remaining)
            if timeout is not None and remaining is not None
            else timeout
            if timeout is not None
            else remaining
        )
        try:
            await asyncio.wait_for(self._events[question_id].wait(), wait)
        except TimeoutError as exc:
            if self.questions[question_id].status == QuestionStatus.open:
                self.questions[question_id].status = QuestionStatus.expired
                self._events[question_id].set()
            raise HumanQuestionError("Question expirée") from exc
        question = self.get(question_id)
        if question.status != QuestionStatus.answered:
            raise HumanQuestionError(
                f"Question {question.status.value} : arrêt humain maintenu"
            )
        return question.answer

    def to_agent_question(self, question_id: str) -> AgentQuestion:
        question = self.get(question_id)
        return AgentQuestion(
            id=question.question_id,
            kind=question.step,
            question=question.text,
            options=question.choices,
            answer=question.answer
            if question.status == QuestionStatus.answered
            else None,
            asked_at=question.asked_at,
            answered_at=utcnow()
            if question.status == QuestionStatus.answered
            else None,
        )
