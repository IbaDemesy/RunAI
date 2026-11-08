import asyncio
import math
import re
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
from runai.framing.holo import Phraser
from runai.framing.interpret import extract_slots, normalize_date_window
from runai.journey import public_origin
from runai.models import Race
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


def _mask_address(text: str) -> str:
    text = re.sub(
        r"\b(?:\d+[a-z]?(?:\s*(?:bis|ter))?\s+)?"
        r"(?:rue|avenue|av\.|boulevard|bd\.|chemin|route|impasse|allée|allee|place)\s+"
        r"[^,;\n\d]+",
        "[redacted address]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b\d+[a-z]?\s+[^,;\n\d]+?\s+"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|drive|way)\b",
        "[redacted address]",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\b\d{5}(?:-\d{4})?\b", "[redacted postcode]", text)


class FramingEngine:
    def __init__(
        self,
        search: CandidateSearch,
        mode: DataMode = DataMode.live,
        phraser: Phraser | None = None,
    ):
        self.search = search
        self.mode = mode
        self.phraser = phraser
        self.sessions: dict[str, FramingSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._missions: dict[str, MissionSnapshot] = {}
        self._manual: set[str] = set()
        self._search_keys: dict[str, tuple] = {}

    def get(self, framing_id: str) -> FramingSession:
        return self.sessions[framing_id].model_copy(deep=True)

    async def create(self, request: FramingCreate) -> FramingSession:
        session = FramingSession(id=uuid4().hex, mode=self.mode, user_id=request.user_id)
        self.sessions[session.id] = session
        self._locks[session.id] = asyncio.Lock()
        return await self.reply(
            session.id,
            FramingReply(revision=0, text=request.text, channel=request.channel),
        )

    @staticmethod
    def _validate(values: dict[SlotName, object]) -> None:
        for name, value in values.items():
            try:
                if name == SlotName.race_date and value is not None:
                    date.fromisoformat(str(value))
                elif (
                    name in (SlotName.distance_km, SlotName.budget, SlotName.nights)
                    and value is not None
                ):
                    number = float(value)
                    if (
                        not math.isfinite(number)
                        or number < 0
                        or (name == SlotName.distance_km and number == 0)
                    ):
                        raise ValueError()
                    if name == SlotName.nights and not number.is_integer():
                        raise ValueError()
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
            values = ({} if choice else extract_slots(reply.text or "")) | reply.corrections
            if not values and not choice and not reply.question_id:
                question = next(
                    (q for q in session.open_questions if len(q.slots) == 1 and not q.choices),
                    None,
                )
            if question and len(question.slots) == 1 and answer and (not question.choices or reply.question_id) and not choice:
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
                    if reply.question_id or (
                        len(answer) <= 60 and not any(c.isdigit() for c in answer)
                    ):
                        values[slot] = answer
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
                values[SlotName.origin] = None if public == public_origin("") else public
            values = {
                name: _mask_address(value) if isinstance(value, str) else value
                for name, value in values.items()
            }
            origin_pending = any(q.slots == [SlotName.origin] for q in session.open_questions)
            if not choice and reply.text and not origin_pending:
                holo_values = await self._holo_fill(session, _mask_address(reply.text), values)
                values = holo_values | values
            if isinstance(window := values.get(SlotName.date_window), str):
                values[SlotName.date_window] = normalize_date_window(window)
            if not values and choice is None and session.turns:
                raise FramingError(guidance)
            self._validate(values)
            if isinstance(origin := values.get(SlotName.origin), str):
                public = public_origin(origin)
                values[SlotName.origin] = None if public == public_origin("") else public
            turn_text = reply.text or reply.choice_id or str(values)
            if isinstance(origin, str):
                turn_text = turn_text.replace(origin, public)
            turn_text = _mask_address(turn_text)
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
            await self._phrase_next_question(session)
            self.sessions[framing_id] = session
            return self.get(framing_id)

    async def _holo_fill(
        self, session: FramingSession, text: str, values: dict[SlotName, object]
    ) -> dict[SlotName, object]:
        """Fill slots missed by the heuristic without overwriting existing values."""
        extract = getattr(self.phraser, "extract", None)
        if not extract:
            return {}
        known = {
            name.value: str(slot.value)
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
            name.value: str(slot.value)
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
                search_key = (
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
            return mission

    async def cancel(self, framing_id: str) -> FramingSession:
        async with self._locks[framing_id]:
            session = self.sessions[framing_id]
            if session.status == FramingStatus.launched:
                raise FramingError("Mission launched: use mission cancellation")
            session.status = FramingStatus.cancelled
            session.summary = None
            session.open_questions = []
            return self.get(framing_id)
