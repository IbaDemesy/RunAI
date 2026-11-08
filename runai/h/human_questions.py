import asyncio
import hashlib
import re
from datetime import datetime, timedelta

from runai.contracts.mission import HumanAnswer, HumanQuestion, QuestionStatus
from runai.models import AgentQuestion, utcnow
from runai.safety import release_attempt

_AFFIRMATION = re.compile(
    r"^\W*(oui|ouais|yes|yep|yeah|ok|okay|d'accord|daccord|si|sí|sim|claro|vale|certo|va bene|"
    r"go|go ahead|vas-y|allez|sure|confirm|confirmed|confirme|je confirme)\W*$",
    re.IGNORECASE,
)


_AFFIRMATION_ANY = re.compile(
    r"\b(oui|ouais|yes|yep|yeah|ok|okay|d'accord|daccord|s[iìí]|sim|claro|vale|certo|va bene|go|allez|sure|"
    r"confirm\w*|proceed|continue\w*|please|merci|gracias|obrigad[oa]|grazie|adelante|avanti|vai|vamos|"
    r"vas-y|fais|fait|do it|d'acord|bien s[uû]r|por favor|per favore|s'il (?:te|vous) pla[iî]t)\b",
    re.IGNORECASE,
)


def _is_bare_affirmation(answer: str) -> bool:
    """Short answer (up to 8 words) whose meaning depends on the question it replies to."""
    text = answer.strip()
    return bool(_AFFIRMATION.match(text)) or (
        len(text.split()) <= 8 and bool(_AFFIRMATION_ANY.search(text))
    )


class HumanQuestionError(Exception):
    """Uncorrelated, expired or unauthorized answer."""


class HumanQuestionNotFound(HumanQuestionError):
    pass


class HumanQuestionRegistry:
    def __init__(self):
        self.questions: dict[str, HumanQuestion] = {}
        self._keys: dict[str, str] = {}
        self._answer_digests: dict[str, str] = {}
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
            raise HumanQuestionError("Question ID already used")
        if question.answer is not None:
            raise HumanQuestionError("Question already answered")
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
            raise HumanQuestionNotFound("Unknown question") from exc

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
            raise HumanQuestionError("Incorrect mission or revision")
        digest = hashlib.sha256(answer.answer.encode()).hexdigest()
        if question.status in (QuestionStatus.answered, QuestionStatus.refused):
            if (
                self._keys.get(question_id) == answer.idempotency_key
                and self._answer_digests.get(question_id) == digest
            ):
                return self.get(question_id)
            if question.status == QuestionStatus.answered:
                raise HumanQuestionError("Question already answered")
        elif question.status != QuestionStatus.open:
            raise HumanQuestionError(f"Question {question.status.value}")
        if question.expires_at and (now or utcnow()) >= question.expires_at:
            question.status = QuestionStatus.expired
            self._events[question_id].set()
            raise HumanQuestionError("Question expired")
        refusal = release_attempt(answer.answer)
        if refusal is None and _is_bare_affirmation(answer.answer):
            refusal = release_attempt(
                f"{question.text} {' '.join(question.choices)} {question.reason or ''} {answer.answer}"
            )
        question.status = (
            QuestionStatus.refused if refusal else QuestionStatus.answered
        )
        question.answer = None if refusal else answer.answer
        if refusal:
            question.reason = refusal
        self._keys[question_id] = answer.idempotency_key
        self._answer_digests[question_id] = digest
        if not refusal:
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
            raise HumanQuestionError("Question expired") from exc
        question = self.get(question_id)
        if question.status != QuestionStatus.answered:
            raise HumanQuestionError(
                f"Question {question.status.value} : human stop maintained"
            )
        return question.answer

    def to_agent_question(self, question_id: str) -> AgentQuestion:
        question = self.get(question_id)
        return AgentQuestion(
            id=question.question_id,
            kind=question.step,
            question=question.text,
            display_text=question.display_text,
            options=question.choices,
            answer=question.answer
            if question.status == QuestionStatus.answered
            else None,
            asked_at=question.asked_at,
            answered_at=utcnow()
            if question.status == QuestionStatus.answered
            else None,
        )
