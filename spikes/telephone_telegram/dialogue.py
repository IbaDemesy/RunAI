"""Logique de dialogue telephonique : courte, deterministe, sans LLM.

Pattern « je m'en occupe, je t'envoie tout » : un run H dure ~10 min, on ne garde pas l'appelant en ligne.
"""

from dataclasses import dataclass, field

from orchestrator import Mission, Orchestrator, parse_request

GREETING = "Bonjour, ici RunAI. Dis-moi ta course, par exemple : trouve-moi un semi en avril et prépare tout."
YES = ("oui", "ouais", "vas-y", "go", "d'accord", "ok", "c'est bon", "je valide")
NO = ("non", "annule", "stop", "laisse tomber")


@dataclass
class Reply:
    text: str
    hangup: bool = False
    mission: Mission | None = None


@dataclass
class CallDialogue:
    orchestrator: Orchestrator
    caller: str
    state: str = "await_request"
    pending_text: str = ""
    history: list = field(default_factory=list)

    async def on_final_transcript(self, text: str) -> Reply | None:
        text = text.strip()
        if not text:
            return None
        self.history.append(("user", text))
        low = text.lower()
        if self.state == "await_request":
            req = parse_request(text)
            if not req.distance:
                return self._say("Quelle distance ? Dix kilomètres, semi ou marathon ?")
            self.pending_text = text
            self.state = "await_confirm"
            when = f" en {req.month}" if req.month else ""
            where = f" à {req.city}" if req.city else ""
            return self._say(
                f"Un {req.distance}{when}{where}, c'est bien ça ? Dis oui pour que je lance les trois agents."
            )
        if self.state == "await_confirm":
            if any(w in low for w in NO):
                self.state = "await_request"
                return self._say("D'accord, j'annule. Redis-moi ta course.")
            if any(w in low for w in YES):
                mission = await self.orchestrator.start_mission(
                    self.pending_text, "phone", self.caller
                )
                self.state = "done"
                reply = self._say(
                    "C'est parti. Je m'en occupe : inscription, hôtel et transport. "
                    "Ça prend une dizaine de minutes, je t'envoie tout par message. Tu valideras et tu paieras toi-même. À tout de suite !",
                    hangup=True,
                )
                reply.mission = mission
                return reply
            return self._say(
                "Je n'ai pas compris. Dis oui pour lancer, ou non pour changer."
            )
        return None

    def _say(self, text: str, hangup: bool = False) -> Reply:
        self.history.append(("runai", text))
        return Reply(text, hangup)
