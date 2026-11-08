"""Phrases (voix ou clavier) → commandes typées. Règles simples FR/EN/PT, sans LLM ni réseau."""

import re
import unicodedata

from runai.voice.models import (
    CommandEvent,
    CommandKind,
    CommandSource,
    CorrectionTarget,
    RaceQuery,
    TranscriptEvent,
    VoiceCommand,
)
from runai.voice.vocabulary import CITIES, HALF_MARATHON_KM, MARATHON_KM, RACES


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation ; même longueur que `text` pour garder les positions."""
    chars = []
    for i, char in enumerate(text):
        base = unicodedata.normalize("NFD", char)[0].lower()
        if base in "’`":
            base = "'"
        elif base in ".," and 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
            pass
        elif not (base.isalnum() or base in "'-€"):
            base = " "
        chars.append(base if len(base) == 1 else " ")
    norm = "".join(chars)
    norm = re.sub(r"\b(?:euh|hum|uh|um|(?<!i'd )(?<!would )like)\b", lambda m: " " * len(m[0]), norm)
    norm = re.sub(r"\b(\w+)(?:\s+\1\b)+", lambda m: m[1] + " " * (len(m[0]) - len(m[1])), norm)
    norm = re.sub(r"\b(\w)-(?=\1\w)", "  ", norm)
    return norm


def _words(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])")


_CANCEL = _words(
    r"annul\w*", "laisse tomber", "abandonne[rz]?", "on abandonne",
    "cancel", "call it off", "forget it", "cancela[r]?", "anula[r]?", "desisto",
)
_PAUSE = _words(
    "pause", "(?<!j')attends?", "attendez", "stop", "arrete[sz]?", "une seconde", "une minute",
    "wait", "hold on", "hang on", "espera", "pausa", "pare",
)
_RESUME_VERB = _words(
    "reprends?", "reprenez", "reprendre", "reprise", "continue[rz]?", "resume", "carry on", "keep going",
    "go on", "continua[r]?", "pode continuar", "podes continuar",
)
_RESUME_OK = _words("vas-y", "vas y", "c'est bon", "c est bon", "siga")
_CORRECTION = _words(
    "change[rz]?", "changement", "modifie[rz]?", "corrige[rz]?", "plutot", "en fait",
    "finalement", "au lieu", "instead", "rather", "actually", "switch", "em vez", "antes",
    "prefiro", "muda[r]?", "altera[r]?",
)
_NEW_MISSION = _words(
    r"inscri[st]?-moi", r"inscri[st]? moi", "inscrire", "je veux (?:courir|faire)",
    "j'aimerais (?:courir|faire)", "je voudrais (?:courir|faire)", "organise", "prepare",
    "sign me up", "register me", "i want to run", "i'd like to run",
    "inscreve-me", "inscreve me", "quero (?:correr|fazer)",
)
_NEGATION_BEFORE = re.compile(
    r"(?:(?<![\w-])n[' ]|(?<![\w-])ne (?:pas |plus )?(?:\w+' ?)?|(?<![\w-])(?:don't|do not|never|nao) )$"
)
_NEGATION_AFTER = re.compile(r"^ +(?:pas|plus|jamais)(?![\w-])")
_MAX_COMMAND_WORDS = 25
_PAUSE_WINDOW_WORDS = 4
_LEADING_NO = re.compile(r"^\s*(?:non|no|nao)(?![\w-])")

_MONTHS = (
    "janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre|"
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
)
_TARGETS: tuple[tuple[CorrectionTarget, re.Pattern[str]], ...] = (
    (CorrectionTarget.registration, _words("registration", "inscription", "inscricao", "dossard")),
    (CorrectionTarget.accommodation, _words(
        "hotel", "hotels", "logement", "hebergement", "chambre", "airbnb", "auberge",
        "appartement", "room", "accommodation", "alojamento", "quarto",
    )),
    (CorrectionTarget.transport, _words(
        "train", "trains", "avion", "vol", "vols", "flight", "flights", "plane", "transport",
        "bus", "comboio", "voo", "aviao",
    )),
    (CorrectionTarget.date, _words(
        "date", "dates", "jour", "jours", "week-end", "weekend", "day", "data", "dia",
        "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
        rf"(?:\d{{1,2}}(?:er)? (?:de )?)?(?:{_MONTHS})",
    )),
    (CorrectionTarget.budget, _words(
        "budget", "prix", "moins cher", "cheaper", "price", "preco", "barato", r"\d+(?:[.,]\d+)? ?(?:€|euros?)",
    )),
    (CorrectionTarget.race, _words(
        "course", "semi", "semi-marathon", "marathon", "distance", "race", "corrida",
        "maratona", "meia", r"\d+(?:[.,]\d+)? ?km",
    )),
)

_DATE = re.compile(
    rf"(?<!\w)(?:\d{{1,2}}(?:er)? (?:de )?(?:{_MONTHS})(?: (?:de )?\d{{4}})?"
    rf"|(?:{_MONTHS}) \d{{1,2}}(?: \d{{4}})?"
    rf"|(?:en|in|em) (?:{_MONTHS})(?: \d{{4}})?)(?!\w)"
)
_HALF = _words("semi", "semi-marathon", "half", "half-marathon", "meia", "meia-maratona", "mezza")
_FULL = _words("marathon", "maratona")
_KM = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?) ?(?:km|k|kilometres?|kilometers?|quilometros?)(?!\w)")
_NUMBER_KM = re.compile(
    r"\b(five|ten|twenty|cinco|dez|vinte|cinq|dix|vingt)\s+(?:k|km|kilometers?|kilometres?|quilometros?)\b"
)
_NUMBERS = dict(zip(
    ("five", "ten", "twenty", "cinco", "dez", "vinte", "cinq", "dix", "vingt"),
    (5, 10, 20, 5, 10, 20, 5, 10, 20), strict=True,
))
_ORIGIN = re.compile(r"\b(?:from|depuis|de|desde|depart de|partindo de|a partir de)\s+$")
_CITY_PATTERNS = tuple((city, _words(*city.aliases)) for city in CITIES)
_RACE_PATTERNS = tuple((race, _words(*(re.escape(a).replace(r"\ ", r"\s+") for a in race.aliases))) for race in RACES)


def extract_race(text: str) -> RaceQuery | None:
    norm = normalize(text)
    query = RaceQuery()
    city_mentions = sorted(
        ((match.start(), city, match) for city, pattern in _CITY_PATTERNS for match in pattern.finditer(norm)),
        key=lambda item: item[0],
    )
    race_norm = norm
    for start, city, match in city_mentions:
        prefix = norm[:start]
        origin = _ORIGIN.search(prefix)
        # A race name's "de Lisboa" is a destination, not a departure.
        race_link = (
            re.search(r"\b(?:semi|marathon|maratona|corrida|course|race)\s+$", prefix[:origin.start()])
            if origin and origin[0].strip() == "de" else None
        )
        if origin and not race_link:
            query.origin = city.name
            race_norm = race_norm[:start] + " " * (match.end() - start) + race_norm[match.end():]
    for race, pattern in _RACE_PATTERNS:
        if pattern.search(race_norm):
            query.name, query.city, query.distance_km = race.name, race.city, race.distance_km
            break
    if query.city is None:
        query.city = next((city.name for _, city, match in city_mentions if race_norm[match.start():match.end()].strip()), None)
    if query.city:
        query.country = next(c.country for c in CITIES if c.name == query.city)
    if query.distance_km is None:
        if _HALF.search(norm):
            query.distance_km = HALF_MARATHON_KM
        elif _FULL.search(norm):
            query.distance_km = MARATHON_KM
        elif match := _KM.search(norm):
            query.distance_km = float(match.group(1).replace(",", "."))
        elif match := _NUMBER_KM.search(norm):
            query.distance_km = float(_NUMBERS[match[1]])
    if match := _DATE.search(norm):
        query.date_text = text[match.start():match.end()]
    return query if query.model_dump(exclude_none=True) else None


def _affirmed(pattern: re.Pattern[str], norm: str) -> re.Match[str] | None:
    """Return the last keyword not negated by its surrounding words."""
    for match in reversed(list(pattern.finditer(norm))):
        before, after = norm[:match.start()], norm[match.end():]
        if not (_NEGATION_BEFORE.search(before) or _NEGATION_AFTER.search(after)):
            return match
    return None


def _is_pause(norm: str) -> bool:
    """Mot d'arrêt en tête d'énoncé (« stop, … », « non attends ») : évite « I don't stop » en pleine phrase."""
    return bool(_affirmed(_PAUSE, " ".join(norm.split()[:_PAUSE_WINDOW_WORDS])))


def _target(norm: str) -> CorrectionTarget | None:
    matches = [(match.start(), target) for target, pattern in _TARGETS if (match := pattern.search(norm))]
    return min(matches, key=lambda item: item[0])[1] if matches else None


def parse_command(text: str) -> VoiceCommand | None:
    """Interpret the last affirmed command while preserving early pause detection."""
    norm = " ".join(normalize(text).split())
    if not norm.strip() or len(norm.split()) > _MAX_COMMAND_WORDS:
        return None
    target = _target(norm)
    race = extract_race(text)

    correction = _affirmed(_CORRECTION, norm)
    leading_no = _LEADING_NO.search(norm) if target or race else None
    mission = _affirmed(_NEW_MISSION, norm)
    resume_verb = _affirmed(_RESUME_VERB, norm)
    resume_ok = _affirmed(_RESUME_OK, norm)
    pause = _is_pause(norm)
    keywords = (_CANCEL, _CORRECTION, _NEW_MISSION, _RESUME_VERB, _RESUME_OK, _PAUSE)
    negated = any(p.search(norm) and not _affirmed(p, norm) for p in keywords)
    if negated:
        leading_no = None
    # « c'est bon » ne vaut reprise qu'en tête d'énoncé : « Le semi de Paris me va, c'est bon » est une mission.
    leading_ok = _affirmed(_RESUME_OK, " ".join(norm.split()[:_PAUSE_WINDOW_WORDS]))
    candidates = []
    for kind, match in (
        (CommandKind.cancel, _affirmed(_CANCEL, norm)),
        (CommandKind.correction, correction or leading_no),
        (CommandKind.new_mission, mission),
        (CommandKind.resume, resume_verb or leading_ok),
        (CommandKind.pause, _affirmed(_PAUSE, norm)),
    ):
        if match and (kind is not CommandKind.pause or pause or candidates):
            candidates.append((match.start(), kind, match))
    if candidates:
        _, kind, match = max(candidates, key=lambda item: item[0])
        target = _target(norm[match.end():])
        if kind is CommandKind.correction:
            return VoiceCommand(kind=kind, target=target or CorrectionTarget.other, race=race, detail=text.strip())
        if kind is CommandKind.new_mission:
            return VoiceCommand(kind=kind, race=race, detail=text.strip())
        return VoiceCommand(kind=kind, target=target, detail=text.strip() if kind is CommandKind.cancel else None)
    implicit = race and race.city and (race.distance_km or race.name) and not (negated or resume_verb or leading_ok or pause)
    if mission or implicit:
        return VoiceCommand(kind=CommandKind.new_mission, race=race, detail=text.strip())

    if resume_verb or resume_ok:
        return VoiceCommand(kind=CommandKind.resume)
    if pause:
        return VoiceCommand(kind=CommandKind.pause)
    return None


def is_pause_request(text: str) -> bool:
    """Barge-in : mot d'arrêt dans une transcription partielle, avant la fin de la phrase."""
    return _is_pause(" ".join(normalize(text).split()))


def command_from_text(text: str, source: CommandSource = CommandSource.keyboard) -> CommandEvent | None:
    """Repli clavier : même parseur, donc même `VoiceCommand` que la phrase dite à voix haute."""
    command = parse_command(text)
    if command is None:
        return None
    return CommandEvent(command=command, source=source, text=text.strip())


class CommandDetector:
    """Transforme le flux de transcriptions en commandes.

    Partiel contenant un mot d'arrêt → `pause` immédiate (`early=True`), une seule fois par énoncé.
    Final → commande complète ; la `pause` finale est ignorée si elle a déjà été émise en avance.
    """

    def __init__(self, early_pause: bool = True):
        self.early_pause = early_pause
        self._paused_utterances: set[str] = set()

    def feed(self, transcript: TranscriptEvent) -> list[CommandEvent]:
        uid = transcript.utterance_id
        if not transcript.is_final:
            if self.early_pause and uid not in self._paused_utterances and is_pause_request(transcript.text):
                self._paused_utterances.add(uid)
                return [self._event(VoiceCommand(kind=CommandKind.pause), transcript, early=True)]
            return []

        command = parse_command(transcript.text)
        already_paused = uid in self._paused_utterances
        self._paused_utterances.discard(uid)
        if command is None or (command.kind is CommandKind.pause and already_paused):
            return []
        return [self._event(command, transcript)]

    @staticmethod
    def _event(command: VoiceCommand, transcript: TranscriptEvent, early: bool = False) -> CommandEvent:
        return CommandEvent(
            command=command,
            source=CommandSource.voice,
            text=transcript.text.strip(),
            utterance_id=transcript.utterance_id,
            language=transcript.language,
            early=early,
        )
