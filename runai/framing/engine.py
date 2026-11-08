import asyncio
import math
import os
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from uuid import uuid4

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.contracts.framing import (
    CandidateSearch,
    FramingChoice,
    FramingConfirm,
    FramingCreate,
    FramingError,
    FramingQuestion,
    FramingReply,
    FramingSession,
    FramingStatus,
    FramingSummary,
    FramingTurn,
    Slot,
    SlotName,
    SlotStatus,
    assert_launchable,
    check_reply_revision,
    format_date,
    format_distance,
    format_money,
    matching_distance,
    missing_slots,
)
from runai.contracts.mission import MissionSnapshot
from runai.framing.holo import TRANSPORTS, Phraser, _mask_address, clean_extraction
from runai.framing.interpret import extract_slots, normalize_date_window
from runai.framing.store import RETENTION_SECONDS, FramingStore
from runai.journey import public_origin
from runai.models import Race
from runai.redaction import mask_address, redact_secrets
from runai.search.candidates import CandidateSearchError, location_hint

OnConfirm = Callable[[FramingSession], Awaitable[MissionSnapshot]]

LABELS = {
    SlotName.city: "Which city or country?",
    SlotName.race: "Which official event (name or URL)?",
    SlotName.race_date: "What is the race date?",
    SlotName.date_window: "Which period (month or season)? Say 'any time' if you are flexible.",
    SlotName.distance_km: "What distance in km?",
    SlotName.origin: "Which city are you departing from?",
    SlotName.budget: "What total budget in euros (or no cap)?",
    SlotName.nights: "How many nights?",
    SlotName.transport_mode: "Which transport: train, plane, car or bus?",
}


def _valid_place(value: object, limit: int = 80) -> bool:
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= limit:
        return False
    normalized = value.strip().casefold().replace("’", "'").strip(".!?")
    return any(c.isalpha() for c in value) and not re.search(
        r"^(?:oui|non|yes|no|none|aucun[e]?|peu importe|n'importe quoi|"
        r"je (?:ne )?sais pas|i (?:don't|do not) know|not sure|"
        r"maybe|perhaps|whatever)(?:\b|$)",
        normalized,
    )


LLM_INTENTS = {"answer", "correction", "advice", "smalltalk", "unclear"}
LLM_SLOTS = {
    SlotName.city, SlotName.origin, SlotName.race, SlotName.distance_km, SlotName.race_date,
    SlotName.date_window, SlotName.edition, SlotName.budget, SlotName.nights, SlotName.transport_mode,
}


_CONTROL = re.compile("[" + chr(0) + "-" + chr(8) + chr(11) + "-" + chr(31) + chr(127) + "-" + chr(159)
                      + chr(0x200B) + "-" + chr(0x200F) + chr(0x2028) + "-" + chr(0x202E) + chr(0x2066) + "-" + chr(0x2069) + "]")


_ANSI = re.compile(chr(27) + r"\[[0-9;?]*[A-Za-z]")


def _clean_text(value):
    """Strip control, zero-width and bidi override characters from what the runner typed."""
    if not isinstance(value, str):
        return value
    return _CONTROL.sub(" ", _ANSI.sub("", value)).strip() if isinstance(value, str) else value


def _norm(text: str) -> str:
    """Case, accent and whitespace-insensitive form used to check quoted evidence."""
    folded = unicodedata.normalize("NFKD", text).casefold()
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def _evidence_in(evidence: str, haystack: str) -> bool:
    """The quote must be a whole-word extract of the message, not a one-letter substring."""
    quote = _norm(evidence)
    if len(quote) < 2 and not quote.isdigit():
        return False
    return re.search(r"(?<!\w)" + re.escape(quote) + r"(?!\w)", haystack) is not None


def _sanitize_ack(value: object, *, allow_question: bool) -> str:
    """Keep the model's short message safe to show: no links, no stray questions, bounded length."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"https?://\S+|www\.\S+", "", value).strip().strip('"«» ')
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not allow_question:
        sentences = [x for x in sentences if "?" not in x]
    text = re.sub(r"\s+", " ", " ".join(sentences)).strip()
    if len(text) > 320:
        text = text[:320].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return redact_secrets(text)


class FramingEngine:
    def __init__(
        self,
        search: CandidateSearch,
        mode: DataMode = DataMode.live,
        phraser: Phraser | None = None,
        store: FramingStore | None = None,
        mission_lookup: Callable[[str], MissionSnapshot | None] | None = None,
    ):
        self.search = search
        self.mode = mode
        self.phraser = phraser
        self.sessions: dict[str, FramingSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._missions: dict[str, MissionSnapshot] = {}
        self._manual: set[str] = set()
        self._search_keys: dict[str, tuple] = {}
        self._origin_misses: dict[str, int] = {}
        self._seen: dict[str, list[str]] = {}
        self._touched: dict[str, float] = {}
        self.store = store
        self.retention_s = store.retention_s if store else RETENTION_SECONDS
        self._mission_lookup = mission_lookup
        for restored in store.load() if store else []:
            self._restore(restored)

    def _restore(self, session: FramingSession) -> None:
        """Rebuild the in-memory bookkeeping that is not part of the persisted session."""
        self.sessions[session.id] = session
        self._locks[session.id] = asyncio.Lock()
        self._touched[session.id] = time.time()
        if session.status in (FramingStatus.cancelled, FramingStatus.launched):
            return
        if not session.selected_candidate_id and any(x.code == "manual_event" for x in session.limitations):
            self._manual.add(session.id)
        if session.candidates or session.selected_candidate_id or session.search_stats:
            # the search already ran for these slots: do not repeat (and overwrite) it on the next reply
            self._search_keys[session.id] = self._search_key(session)

    def _forget(self, framing_id: str, *, session: bool = False) -> None:
        """Drop per-conversation bookkeeping (and the conversation itself once expired)."""
        self._manual.discard(framing_id)
        self._search_keys.pop(framing_id, None)
        self._origin_misses.pop(framing_id, None)
        self._seen.pop(framing_id, None)
        if session:
            self.sessions.pop(framing_id, None)
            self._locks.pop(framing_id, None)
            self._touched.pop(framing_id, None)
            if self.store:
                self.store.delete(framing_id)

    def purge_expired(self, now: float | None = None) -> int:
        """Forget conversations idle for longer than the retention; never one being handled."""
        now = time.time() if now is None else now
        expired = [
            framing_id for framing_id, touched in self._touched.items()
            if now - touched > self.retention_s
            and (lock := self._locks.get(framing_id)) is not None and not lock.locked()
        ]
        for framing_id in expired:
            session = self.sessions.get(framing_id)
            if session and session.mission_id:
                self._missions.pop(session.mission_id, None)
            self._forget(framing_id, session=True)
        return len(expired)

    def get(self, framing_id: str) -> FramingSession:
        return self.sessions[framing_id].model_copy(deep=True)

    async def create(self, request: FramingCreate) -> FramingSession:
        self.purge_expired()
        session = FramingSession(id=uuid4().hex, mode=self.mode, user_id=request.user_id)
        self.sessions[session.id] = session
        self._locks[session.id] = asyncio.Lock()
        self._touched[session.id] = time.time()
        return await self.reply(
            session.id,
            FramingReply(revision=0, text=request.text, channel=request.channel),
        )

    @staticmethod
    def _validate(values: dict[SlotName, object]) -> None:
        for name, value in values.items():
            try:
                if name in (SlotName.city, SlotName.origin, SlotName.race) and value is not None:
                    if not _valid_place(value, 200 if name == SlotName.race else 80):
                        raise ValueError()
                elif name == SlotName.race_date and value is not None:
                    if date.fromisoformat(str(value)) < date.today():
                        raise ValueError()
                elif name == SlotName.transport_mode and value is not None:
                    if not isinstance(value, str) or value not in TRANSPORTS:
                        raise ValueError()
                elif (
                    name in (SlotName.distance_km, SlotName.budget, SlotName.nights)
                    and value is not None
                ):
                    number = float(value)
                    if (
                        not math.isfinite(number)
                        or number < 0
                        or (name in (SlotName.distance_km, SlotName.budget) and number == 0)
                        or (name == SlotName.distance_km and number > 400)
                        or (name == SlotName.nights and number > 30)
                    ):
                        raise ValueError()
                    if name == SlotName.nights and not number.is_integer():
                        raise FramingError("Please enter a whole number for nights.")
                elif value is None and name != SlotName.budget:
                    continue
                elif name not in (
                    SlotName.budget,
                    SlotName.nights,
                    SlotName.distance_km,
                ) and (not isinstance(value, str) or not value.strip()):
                    raise ValueError()
            except (ValueError, TypeError, OverflowError) as exc:
                raise FramingError(f"Invalid value: {name.value}") from exc

    async def reply(self, framing_id: str, reply: FramingReply) -> FramingSession:
        async with self._locks[framing_id]:
            session = self.get(framing_id)
            reply = reply.model_copy(update={
                "text": _clean_text(reply.text),
                "corrections": {name: _clean_text(value) for name, value in reply.corrections.items()},
            })
            if reply.client_message_id and reply.client_message_id in self._seen.get(framing_id, ()):
                return session  # duplicate delivery of a message already processed
            if self._stale_but_compatible(session, reply):
                reply = reply.model_copy(update={"revision": session.revision})
            check_reply_revision(session, reply)
            for turn in session.turns:
                turn.text = _mask_address(turn.text)
            question = next(
                (q for q in session.open_questions if q.id == reply.question_id), None
            )
            if reply.question_id and question is None:
                raise FramingError("Stale or unknown question")
            answer = (reply.text or "").strip()
            guidance = (
                "Please enter a city, race name, or an explicit correction; "
                "answer the next question or type 'none' to reject the suggested races."
            )
            if (
                reply.text is not None
                and not reply.choice_id
                and not reply.corrections
                and (
                    (bool(session.turns) and len(answer) > 500)
                    or not any(c.isalnum() for c in answer)
                )
            ):
                raise FramingError(guidance)
            choice = None
            if reply.choice_id:
                choice = next(
                    (
                        c
                        for q in session.open_questions
                        for c in q.choices
                        if c.id == reply.choice_id
                        and (question is None or q.id == question.id)
                    ),
                    None,
                )
                if choice is None:
                    raise FramingError("Unknown choice")
            elif answer.casefold() in {
                "none", "aucune", "no", "other", "autre", "not this one"
            }:
                choice = next(
                    (
                        c
                        for q in session.open_questions
                        for c in q.choices
                        if c.id == "none" and (question is None or q.id == question.id)
                    ),
                    None,
                )
            pending = question or next(iter(session.open_questions), None)
            holo_values: dict[SlotName, object] = {}
            values: dict[SlotName, object] = {}
            llm_ack = None
            decision = None
            if answer and reply.text and not choice and not reply.corrections:
                decision = await self._decide(session, answer, pending)
            if decision is not None:
                if not decision["values"] and decision.get("origin_rejected"):
                    retry = self._origin_retry(framing_id)
                    if retry:
                        return self._clarify(session, reply, self._with_question(session, retry, "answer"))
                    decision["values"] = {SlotName.origin: public_origin("")}
                if not decision["values"]:
                    return self._clarify(
                        session, reply,
                        self._with_question(session, decision["message"] or guidance, decision["intent"]),
                    )
                values = dict(decision["values"])
                llm_ack = decision["message"]
            else:
                pending = question or next(iter(session.open_questions), None)
                if (
                    pending and pending.choices and answer and not choice
                    and not reply.corrections
                    and not re.search(
                        r"https?://|\b(?:marathon|semi|half|run|race|trail|course|corrida|foulées|\d+\s*km?)\b",
                        answer,
                        re.IGNORECASE,
                    )
                ):
                    return self._clarify(session, reply, "Please select an event from the choices, or choose 'None of these' to clarify your search.")
                correction = re.match(
                    r"^(?:(?:en fait|actually)[,\s]+)?(?:plutôt|rather|instead)[,\s]+(.+?)\s*[.!?]?$"
                    r"|^(?:en fait|actually)[,\s]+(.+?)\s*[.!?]?$",
                    answer, re.IGNORECASE,
                )
                corrected_city = None
                if correction and pending and pending.slots[0] in (SlotName.city, SlotName.origin):
                    corrected_city = next(group for group in correction.groups() if group)
                    if not _valid_place(corrected_city) or not re.fullmatch(
                        r"[^\W\d_]+(?:[ '\u2019-][^\W\d_]+){0,4}", corrected_city
                    ):
                        return self._clarify(session, reply, "Please specify the race city you want instead.")
                if (
                    pending and pending.slots[0] in (SlotName.city, SlotName.origin, SlotName.race)
                    and answer and not choice and not reply.corrections
                    and not corrected_city
                    and not _valid_place(answer, 200 if pending.slots[0] == SlotName.race else 80)
                ):
                    return self._clarify(session, reply, "Please provide a city or official race name (2–80 characters), or clarify your request.")
                values = ({} if choice else extract_slots(reply.text or "")) | reply.corrections
                if corrected_city:
                    values = {SlotName.city: corrected_city} | reply.corrections
                if not values and not choice and not reply.question_id:
                    question = next(
                        (q for q in session.open_questions if len(q.slots) == 1 and not q.choices),
                        None,
                    )
                if question and len(question.slots) == 1 and answer and not question.choices and not choice and not corrected_city:
                    slot = question.slots[0]
                    if slot == SlotName.date_window and slot not in values:
                        answer = reply.text.strip()
                        normalized = answer.casefold()
                        flexible = (
                            "peu importe",
                            "n'importe",
                            "n’importe",
                            "flexible",
                            "pas de pr\u00e9f\u00e9rence",
                            "any time",
                            "anytime",
                            "doesn't matter",
                            "does not matter",
                            "whenever",
                            "no preference",
                        )
                        if any(phrase in normalized for phrase in flexible):
                            values[slot] = None
                        else:
                            values[slot] = (
                                extract_slots(reply.text).get(slot) or answer
                            )
                    elif (
                        slot == SlotName.budget
                        and slot not in values
                        and reply.text.strip().casefold() in (
                            "no cap", "no limit", "unlimited", "sans plafond", "pas de limite",
                        )
                    ):
                        values[slot] = None
                    elif (
                        slot in (SlotName.city, SlotName.origin, SlotName.race)
                        and slot not in values
                        and (reply.question_id or not values)
                    ):
                        candidate = public_origin(answer) if slot == SlotName.origin else answer
                        if _valid_place(candidate) and (reply.question_id or (
                            len(answer) <= 60 and not any(c.isdigit() for c in answer)
                        )):
                            values[slot] = candidate.strip()
                    elif not values and slot in (
                        SlotName.distance_km,
                        SlotName.budget,
                        SlotName.nights,
                    ):
                        try:
                            values[slot] = float(answer.replace(",", "."))
                            self._validate(values)
                        except (ValueError, FramingError) as exc:
                            raise FramingError(
                                f"Please enter a valid number for {slot.value}."
                            ) from exc
                holo_values = {}
                if isinstance(origin := values.get(SlotName.origin), str):
                    public = public_origin(origin)
                    if public == public_origin(""):
                        retry = self._origin_retry(framing_id)
                        if retry:
                            # clear the origin (it is asked again) and say why, instead of looping silently
                            llm_ack = retry
                            public = None
                    else:
                        self._origin_misses.pop(framing_id, None)
                    values[SlotName.origin] = public
                values = {
                    name: _mask_address(value)
                    if name in (SlotName.origin, SlotName.preferences) and isinstance(value, str)
                    else value
                    for name, value in values.items()
                }
                origin_pending = any(q.slots == [SlotName.origin] for q in session.open_questions)
                if not choice and reply.text and not origin_pending:
                    holo_values = await self._holo_fill(session, mask_address(_mask_address(reply.text)), values)
                    values = holo_values | values
            if isinstance(window := values.get(SlotName.date_window), str):
                values[SlotName.date_window] = normalize_date_window(window)
            if not values and choice is None and session.turns:
                if answer and session.open_questions:
                    return self._clarify(session, reply, guidance)
                raise FramingError(guidance)
            self._validate(values)
            for name in (SlotName.budget, SlotName.nights, SlotName.distance_km):
                if values.get(name) is not None:
                    number = float(values[name])
                    values[name] = int(number) if name == SlotName.nights else number
            if isinstance(origin := values.get(SlotName.origin), str):
                public = public_origin(origin)
                values[SlotName.origin] = public
            turn_text = reply.text or reply.choice_id or "; ".join(
                f"{name.value}: {value}" for name, value in values.items()
            )
            if isinstance(origin, str):
                turn_text = turn_text.replace(origin, public)
            turn_text = mask_address(_mask_address(turn_text))
            session.revision += 1
            session.summary = None
            session.confirm_key = session.confirmed_revision = None
            session.status = FramingStatus.collecting
            discovery_changed = any(
                name in values
                and session.slots[name].is_known
                and not (
                    name == SlotName.date_window
                    and name in holo_values
                    and session.slots[name].value is None
                )
                and values[name] != session.slots[name].value
                for name in (
                    SlotName.city,
                    SlotName.race,
                    SlotName.distance_km,
                    SlotName.date_window,
                    SlotName.race_date,
                    SlotName.edition,
                )
            )
            if discovery_changed:
                self._drop_candidate_limitations(session)
                session.search_stats = None
                self._manual.discard(framing_id)
                self._search_keys.pop(framing_id, None)
                session.selected_candidate_id = None
                session.candidates = []
                for name, old in list(session.slots.items()):
                    if old.status == SlotStatus.sourced and name in (
                        SlotName.race, SlotName.race_date, SlotName.distance_km,
                        SlotName.edition, SlotName.date_window,
                    ):
                        session.slots[name] = Slot(name=name)
            for name, value in values.items():
                session.slots[name] = Slot(
                    name=name,
                    status=SlotStatus.answered
                    if value is not None
                    else SlotStatus.unknown,
                    value=value,
                    provenance=Provenance(
                        kind="derived", label="Distance from the human term marathon/half-marathon"
                    )
                    if name == SlotName.distance_km
                    and name not in reply.corrections
                    and not re.search(r"\b\d+(?:[.,]\d+)?\s*k(?:m)?\b", reply.text or "", re.IGNORECASE)
                    else Provenance(kind="human"),
                    revision=session.revision,
                )
                if name in (SlotName.budget, SlotName.date_window) and value is None:
                    session.slots[name].status = SlotStatus.not_needed
            if choice and choice.candidate_id:
                candidate = next(
                    c for c in session.candidates if c.id == choice.candidate_id
                )
                session.selected_candidate_id = candidate.id
                distance = session.slots[SlotName.distance_km]
                if (
                    distance.is_known
                    and distance.value is not None
                    and candidate.distances_km
                    and matching_distance(
                        candidate.distances_km, float(distance.value)
                    )
                    is None
                ):
                    if len(candidate.distances_km) == 1:
                        distance.value = candidate.distances_km[0]
                        distance.status = SlotStatus.sourced
                        distance.provenance = candidate.provenance
                    else:
                        session.slots[SlotName.distance_km] = Slot(
                            name=SlotName.distance_km
                        )
                sourced = {
                    SlotName.race: candidate.name,
                    SlotName.city: candidate.city,
                    SlotName.race_date: candidate.race_date,
                }
                if candidate.race_date:
                    sourced[SlotName.edition] = str(candidate.race_date.year)
                if (
                    len(candidate.distances_km) == 1
                    and not session.slots[SlotName.distance_km].is_known
                ):
                    sourced[SlotName.distance_km] = candidate.distances_km[0]
                for name, value in sourced.items():
                    if value is not None and (not isinstance(value, str) or value.strip()):
                        session.slots[name] = Slot(
                            name=name,
                            value=value,
                            status=SlotStatus.sourced,
                            provenance=candidate.provenance,
                            revision=session.revision,
                        )
                self._drop_candidate_limitations(session)
                session.limitations.extend(candidate.limitations)
            elif choice:
                session.candidates = []
                self._manual.add(framing_id)
            session.turns.append(
                FramingTurn(
                    role="user",
                    text=turn_text,
                    channel=reply.channel,
                    revision=session.revision,
                )
            )
            await self._advance(session, search=choice is None)
            for limitations in [session.limitations] + [c.limitations for c in session.candidates]:
                for limitation in limitations:
                    if limitation.code == "close_match":
                        limitation.message = "Close to your request, but not an exact match."
            if llm_ack:
                self._append_ack(session, llm_ack)
            else:
                await self._phrase_next_question(session)
            self.sessions[framing_id] = session
            self._touched[framing_id] = time.time()
            self._mark_seen(framing_id, reply)
            self._persist(session)
            return self.get(framing_id)

    async def _decide(self, session: FramingSession, text: str, pending) -> dict | None:
        """LLM-first turn: the model proposes slot updates, this code validates every one of them.

        Returns None when no LLM is configured or it failed, so the deterministic path takes over.
        """
        decide = getattr(self.phraser, "decide", None)
        if decide is None or os.getenv("RUNAI_FRAMING_LLM", "1").strip().lower() in {"0", "false", "off", "no"}:
            return None
        known = {
            name.value: str(slot.value)
            for name, slot in session.slots.items()
            if slot.is_known and slot.value is not None
        }
        try:
            raw = await decide(_mask_address(text), known, session.turns, pending.text if pending else "")
        except Exception:  # noqa: BLE001 - a failing model must never break the conversation
            return None
        if not isinstance(raw, dict):
            return None
        intent = raw.get("intent") if raw.get("intent") in LLM_INTENTS else "answer"
        values: dict[SlotName, object] = {}
        origin_rejected = False
        haystack = _norm(_mask_address(text))
        updates = raw.get("updates")
        for update in updates if isinstance(updates, list) else []:
            if not isinstance(update, dict):
                continue
            try:
                name = SlotName(update.get("slot"))
            except ValueError:
                continue
            if name not in LLM_SLOTS:
                continue
            evidence = update.get("evidence")
            if not isinstance(evidence, str) or not _evidence_in(evidence, haystack):
                continue  # unquoted, too short or invented: reject
            current = session.slots[name]
            known_value = current.is_known and current.value is not None
            # a known slot is only overwritten by an explicit correction or by the answer to its own question
            may_replace = bool(update.get("replaces_previous")) and (
                intent == "correction" or (pending is not None and name in pending.slots)
            )
            value = update.get("value")
            if value is None:
                if name in (SlotName.budget, SlotName.date_window) and (not known_value or may_replace):
                    values[name] = None
                continue
            if name in (SlotName.city, SlotName.origin, SlotName.race) and not isinstance(value, str):
                continue
            if name == SlotName.origin:
                value = _mask_address(public_origin(value))
                if value == public_origin("") or not _valid_place(value):
                    origin_rejected = True
                    continue
            if name in (SlotName.city, SlotName.origin, SlotName.race) and _norm(value) not in haystack:
                continue  # a place or event name must be written in the message itself
            if name in (SlotName.city, SlotName.race):
                if not _valid_place(value, 200 if name == SlotName.race else 80):
                    continue
                value = value.strip()
            else:
                value = clean_extraction({name.value: value}).get(name.value)
            if value is None:
                continue
            try:
                self._validate({name: value})
            except FramingError:
                continue
            if known_value and str(current.value) == str(value):
                continue
            if known_value and not may_replace:
                continue
            values[name] = value
        return {"intent": intent, "values": values, "origin_rejected": origin_rejected,
                "message": _sanitize_ack(raw.get("message"), allow_question=intent == "unclear")}

    @staticmethod
    def _search_key(session: FramingSession, place: str | None = None) -> tuple:
        if place is None:
            place = location_hint(" / ".join(t.text for t in session.turns if t.role == "user" and t.text))
        date_window = session.slots[SlotName.date_window]
        return (
            session.slots[SlotName.city].value,
            session.slots[SlotName.race].value,
            session.slots[SlotName.distance_km].value,
            date_window.value,
            date_window.status,
            session.slots[SlotName.race_date].value,
            session.slots[SlotName.edition].value,
            session.slots[SlotName.preferences].value,
            place,
        )

    @staticmethod
    def _stale_but_compatible(session: FramingSession, reply: FramingReply) -> bool:
        """An older-revision reply is replayed on the current state when nothing it targets changed."""
        if not 0 <= reply.revision < session.revision or reply.choice_id:
            return False
        if reply.question_id:
            return any(q.id == reply.question_id for q in session.open_questions)
        return bool(reply.corrections) and not reply.text and all(
            session.slots[name].revision <= reply.revision for name in reply.corrections
        )

    @staticmethod
    def _drop_candidate_limitations(session: FramingSession) -> None:
        stale = {(x.code, x.message) for c in session.candidates for x in c.limitations}
        session.limitations = [x for x in session.limitations if (x.code, x.message) not in stale]

    def _persist(self, session: FramingSession) -> None:
        if self.store:
            self.store.save(session)

    def _origin_retry(self, framing_id: str) -> str | None:
        """Ask for a city when the origin was only a street address; give up after two tries."""
        misses = self._origin_misses.get(framing_id, 0) + 1
        if misses > 2:
            self._origin_misses.pop(framing_id, None)
            return None
        self._origin_misses[framing_id] = misses
        return "I only need the city or neighbourhood you leave from, not a street address."

    @staticmethod
    def _next_question_text(session: FramingSession) -> str:
        if not session.open_questions:
            return ""
        question = next(
            (q for q in session.open_questions if not any(c.candidate_id for c in q.choices)),
            session.open_questions[0],
        )
        if any(c.candidate_id for c in question.choices):
            return "Select the race you want below, or tell me if none is suitable."
        return question.text

    def _with_question(self, session: FramingSession, message: str, intent: str) -> str:
        if intent == "unclear" and "?" in message:
            return message
        return f"{message} {self._next_question_text(session)}".strip()

    def _append_ack(self, session: FramingSession, ack: str) -> None:
        text = f"{ack} {self._next_question_text(session)}".strip()
        session.turns.append(FramingTurn(role="assistant", text=text, revision=session.revision))

    def _clarify(self, session: FramingSession, reply: FramingReply, message: str) -> FramingSession:
        session.revision += 1
        if session.summary is not None:
            # nothing was learned: the summary is still true, so keep it valid for the new revision
            session.summary.revision = session.revision
        session.confirm_key = session.confirmed_revision = None
        for question in session.open_questions:
            question.revision = session.revision
        session.turns.extend([
            FramingTurn(role="user", text=_mask_address(reply.text or ""), channel=reply.channel, revision=session.revision),
            FramingTurn(role="assistant", text=message, revision=session.revision),
        ])
        self.sessions[session.id] = session
        self._touched[session.id] = time.time()
        self._mark_seen(session.id, reply)
        self._persist(session)
        return self.get(session.id)

    def _mark_seen(self, framing_id: str, reply: FramingReply) -> None:
        if reply.client_message_id:
            seen = self._seen.setdefault(framing_id, [])
            seen.append(reply.client_message_id)
            del seen[:-20]

    async def _holo_fill(
        self, session: FramingSession, text: str, values: dict[SlotName, object]
    ) -> dict[SlotName, object]:
        """Fill slots missed by the heuristic without overwriting existing values."""
        extract = getattr(self.phraser, "extract", None)
        if not extract:
            return {}
        known = {
            name.value: mask_address(str(slot.value))
            for name, slot in session.slots.items()
            if slot.is_known
            and not (
                name == SlotName.date_window
                and slot.provenance
                and slot.provenance.kind == "derived"
            )
        }
        filled: dict[SlotName, object] = {}
        for raw, value in (await extract(text, known, session.turns)).items():
            try:
                name = SlotName(raw)
            except ValueError:
                continue
            if name in values or name.value in known:
                continue
            try:
                self._validate({name: value})
            except FramingError:
                continue
            filled[name] = value
        return filled

    async def _phrase_next_question(self, session: FramingSession) -> None:
        if not self.phraser or not session.open_questions:
            return
        question = next(
            (q for q in session.open_questions if not any(c.candidate_id for c in q.choices)),
            session.open_questions[0],
        )
        known = {
            name.value: mask_address(str(slot.value))
            for name, slot in session.slots.items()
            if slot.is_known and slot.value is not None
        }
        candidates = [c for c in question.choices if c.candidate_id]
        if candidates:
            count = len(candidates)
            text = (
                "I found a matching race. Review it below and select it, or tell me if it is not the right one."
                if count == 1
                else f"I found {count} matching races. Select the one you want below, or tell me if none is suitable."
            )
        else:
            text = await self.phraser.phrase(session.turns, question.text, known)
        session.turns.append(
            FramingTurn(role="assistant", text=text, revision=session.revision)
        )

    async def _advance(self, session: FramingSession, *, search: bool) -> None:
        session.open_questions = []
        race_date = session.slots[SlotName.race_date]
        date_window = session.slots[SlotName.date_window]
        if (
            (not race_date.is_known or race_date.value is None)
            and date_window.provenance
            and date_window.provenance.kind == "derived"
        ):
            session.slots[SlotName.date_window] = Slot(name=SlotName.date_window)
        if race_date.is_known and race_date.value is not None and (
            not date_window.is_known
            or (date_window.provenance and date_window.provenance.kind == "derived")
        ):
            session.slots[SlotName.date_window] = Slot(
                name=SlotName.date_window,
                status=race_date.status,
                value=str(race_date.value),
                provenance=Provenance(kind="derived"),
                revision=session.revision,
            )
        request_text = " / ".join(
            turn.text for turn in session.turns if turn.role == "user" and turn.text
        )
        place = location_hint(request_text)
        if not session.selected_candidate_id and session.id not in self._manual:
            prerequisites = []
            if (
                not session.slots[SlotName.city].is_known
                and not session.slots[SlotName.race].is_known
                and not place
            ):
                prerequisites.append(SlotName.city)
            if (
                not session.slots[SlotName.distance_km].is_known
                and not session.slots[SlotName.race].is_known
            ):
                prerequisites.append(SlotName.distance_km)
            if (
                not session.slots[SlotName.date_window].is_known
                and not session.slots[SlotName.race_date].is_known
                and not session.slots[SlotName.race].is_known
            ):
                prerequisites.append(SlotName.date_window)
            prerequisites.extend(
                name
                for name in missing_slots(session)
                if name
                in (
                    SlotName.origin,
                    SlotName.budget,
                    SlotName.nights,
                    SlotName.transport_mode,
                )
            )
            if prerequisites:
                session.status = FramingStatus.collecting
                for name in prerequisites:
                    session.open_questions.append(
                        FramingQuestion(
                            id=uuid4().hex,
                            slots=[name],
                            text=LABELS[name],
                            revision=session.revision,
                        )
                    )
                return
            if search:
                date_window = session.slots[SlotName.date_window]
                search_key = self._search_key(session, place)
                if self._search_keys.get(session.id) != search_key:
                    self._search_keys[session.id] = search_key
                    session.limitations = [
                        limitation
                        for limitation in session.limitations
                        if limitation.code
                        not in {
                            "no_candidates",
                            "candidate_provider_error",
                            "fixture_missing",
                            "demo_closest",
                        }
                    ]
                    try:
                        session.search_stats = None
                        if hasattr(self.search, "search"):
                            if place:
                                result = await self.search.search(
                                    session.slots, request_text=request_text
                                )
                            else:
                                result = await self.search.search(session.slots)
                            session.candidates = result.candidates
                            session.search_stats = result.search_stats
                            session.limitations.extend(result.limitations)
                        elif place:
                            session.candidates = await self.search.find_candidates(
                                session.slots, request_text=request_text
                            )
                        else:
                            session.candidates = await self.search.find_candidates(
                                session.slots
                            )
                    except CandidateSearchError as exc:
                        session.search_stats = exc.search_stats
                        self._search_keys.pop(session.id, None)
                        session.candidates = []
                        session.limitations.append(
                            Limitation(
                                code="candidate_provider_error",
                                message="Race search is temporarily unavailable. Please try again or provide the official event details.",
                            )
                        )
                    if not session.candidates and not any(
                        limitation.code == "no_candidates"
                        for limitation in session.limitations
                    ):
                        session.limitations.append(
                            Limitation(
                                code="no_candidates",
                                message=(
                                    "I found no matching race, even after broadening the search. "
                                    "Provide the official race name or its website URL."
                                ),
                            )
                        )
        if session.candidates and not session.selected_candidate_id:
            session.status = FramingStatus.choosing_candidate
            close_matches_only = all(
                any(limitation.code == "close_match" for limitation in candidate.limitations)
                for candidate in session.candidates
            )
            session.open_questions.append(
                FramingQuestion(
                    id=uuid4().hex,
                    slots=[SlotName.race],
                    text=(
                        "I could not find your exact race. Here are the closest matches — "
                        "which one interests you?"
                        if close_matches_only
                        else "Which event would you like? Check the sources and edition."
                    ),
                    revision=session.revision,
                    choices=[
                        FramingChoice(
                            id=c.id,
                            candidate_id=c.id,
                            label=(
                                f"{c.name} — {format_date(c.race_date) if c.race_date else 'date to be confirmed'}"
                                + (
                                    " · close to your request"
                                    if any(
                                        limitation.code == "close_match"
                                        for limitation in c.limitations
                                    )
                                    else ""
                                )
                            ),
                            value=c.model_dump(mode="json"),
                        )
                        for c in session.candidates
                    ]
                    + [FramingChoice(id="none", label="None of these, let me clarify")],
                )
            )
            return
        candidate = next(
            (c for c in session.candidates if c.id == session.selected_candidate_id),
            None,
        )
        if candidate and not session.slots[SlotName.race_date].is_known:
            missing = [SlotName.race_date]
        else:
            missing = missing_slots(session)
            if not session.slots[SlotName.city].is_known:
                missing.insert(0, SlotName.city)
        distance = session.slots[SlotName.distance_km]
        race_km = float(distance.value) if distance.is_known else None
        if candidate and candidate.distances_km and race_km is not None:
            race_km = matching_distance(candidate.distances_km, race_km)
            if race_km is None:
                raise FramingError("Distance not offered by this event")
        for name in missing:
            session.open_questions.append(
                FramingQuestion(
                    id=uuid4().hex,
                    slots=[name],
                    text=LABELS[name],
                    revision=session.revision,
                )
            )
        if missing:
            return
        value = lambda name: session.slots[name].value
        race = (
            candidate.to_race(race_km)
            if candidate
            else Race(
                name=value(SlotName.race),
                city=value(SlotName.city),
                country="",
                distance_km=float(value(SlotName.distance_km)),
            )
        )
        race.city = value(SlotName.city)
        race.race_date = date.fromisoformat(str(value(SlotName.race_date)))
        if not candidate and not any(
            l.code == "manual_event" for l in session.limitations
        ):
            session.limitations.append(
                Limitation(
                    code="manual_event",
                    message="User-provided event, not verified: manually check the official website and country before any automation.",
                )
            )
        nights = int(value(SlotName.nights))
        dates = (
            (
                race.race_date - timedelta(days=nights - 1),
                race.race_date + timedelta(days=1),
            )
            if nights
            else (race.race_date, race.race_date)
        )
        session.summary = FramingSummary(
            revision=session.revision,
            race=race,
            candidate_id=session.selected_candidate_id,
            origin_public=public_origin(value(SlotName.origin)),
            date_range=dates,
            nights=nights,
            budget_eur=value(SlotName.budget),
            transport_mode=value(SlotName.transport_mode),
            lines=[
                f"{race.name}, {race.city}, {format_date(race.race_date)}, {format_distance(race.distance_km)}",
                f"From {value(SlotName.origin)} · {nights} {'night' if nights == 1 else 'nights'} · {value(SlotName.transport_mode)}",
                f"Budget: {format_money(value(SlotName.budget))}",
            ],
            limitations=session.limitations,
        )
        session.status = FramingStatus.ready_to_confirm

    async def confirm(
        self, framing_id: str, request: FramingConfirm, on_confirm: OnConfirm
    ) -> MissionSnapshot:
        async with self._locks[framing_id]:
            session = self.sessions[framing_id]
            mission_id = assert_launchable(session, request)
            if mission_id:
                if mission_id not in self._missions:
                    # after a restart the in-memory replay cache is empty: ask the mission service
                    found = self._lookup_mission(mission_id)
                    if found is None:
                        raise FramingError("Mission already launched: open it from your trip page")
                    self._missions[mission_id] = found
                return self._missions[mission_id].model_copy(deep=True)
            session.status = FramingStatus.confirmed
            session.confirmed_revision = session.revision
            session.confirm_key = request.idempotency_key
            try:
                mission = await on_confirm(session.model_copy(deep=True))
            except BaseException:
                session.status = FramingStatus.ready_to_confirm
                session.confirm_key = session.confirmed_revision = None
                raise
            session.status = FramingStatus.launched
            session.mission_id = mission.mission_id
            self._missions[mission.mission_id] = mission.model_copy(deep=True)
            self._forget(framing_id)
            self._touched[framing_id] = time.time()
            self._persist(session)
            return mission

    def _lookup_mission(self, mission_id: str) -> MissionSnapshot | None:
        if self._mission_lookup is None:
            return None
        try:
            return self._mission_lookup(mission_id)
        except Exception:  # noqa: BLE001 - unknown mission: fall back to the explicit refusal
            return None

    async def cancel(self, framing_id: str) -> FramingSession:
        async with self._locks[framing_id]:
            session = self.sessions[framing_id]
            if session.status == FramingStatus.launched:
                raise FramingError("Mission launched: use mission cancellation")
            session.status = FramingStatus.cancelled
            session.summary = None
            session.open_questions = []
            session.candidates = []
            self._forget(framing_id)
            self._touched[framing_id] = time.time()
            self._persist(session)
            return self.get(framing_id)
