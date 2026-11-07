import re

from runai.models import StopPoint

STOP_INSTRUCTIONS = """\
Règles de sécurité absolues :
- N'effectue aucun paiement, aucune réservation et aucune soumission définitive.
- Ne crée aucun compte et ne saisis aucun mot de passe.
- Ne coche aucune case de consentement, de règlement ou de déclaration de santé.
- Arrête-toi dès que l'étape suivante demanderait l'une de ces actions, et décris précisément l'écran atteint.
"""

_PATTERNS: dict[StopPoint, re.Pattern[str]] = {
    StopPoint.payment: re.compile(
        r"\b(pay(er|ment|ez)?|paiement|checkout|card number|num[ée]ro de carte|cvv|cvc|pagamento|pagar|paga)\b",
        re.IGNORECASE,
    ),
    StopPoint.account_creation: re.compile(
        r"\b(create (an )?account|cr[ée]er (un )?compte|mot de passe|password|palavra-passe|criar conta|crea account)\b",
        re.IGNORECASE,
    ),
    StopPoint.health_declaration: re.compile(
        r"\b(certificat m[ée]dical|medical certificate|health declaration|d[ée]claration de sant[ée]|pps|atestado m[ée]dico|certificato medico)\b",
        re.IGNORECASE,
    ),
    StopPoint.consent: re.compile(
        r"\b(j'accepte|i agree|accept (the )?terms|cgu|cgv|r[èe]glement|terms and conditions|aceito|accetto)\b",
        re.IGNORECASE,
    ),
    StopPoint.submission: re.compile(
        r"\b(confirm(er)? (l'|my |the )?(inscription|registration|booking|r[ée]servation)|submit|soumettre|valider (l'|mon |la )?(inscription|r[ée]servation)"
        r"|r[ée]server|book now|reserve now|inscrever agora|confirmar (inscri[çc][ãa]o|reserva)|reservar"
        r"|conferma (l'|la )?(iscrizione|prenotazione)|prenota (ora|adesso))\b",
        re.IGNORECASE,
    ),
}


def guard_task(task: str) -> str:
    task = task.strip()
    if task.endswith(STOP_INSTRUCTIONS.strip()):
        return f"{task}\n"
    return f"{task}\n\n{STOP_INSTRUCTIONS}"


_NEGATION = re.compile(
    r"\b(aucun|aucune|pas d[e']|pas de la|sans|ni|jamais|no|not|without|never|nenhum|nenhuma|sem|nessun|nessuna|senza)"
    r"(?:\s+[\w'\-]+){0,2}\s*$",
    re.IGNORECASE,
)


def detect_stop_point(text: str) -> StopPoint | None:
    for stop_point, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            if not _NEGATION.search(text[max(0, match.start() - 40) : match.start()]):
                return stop_point
    return None
