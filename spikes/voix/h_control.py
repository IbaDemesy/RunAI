"""Pilotage d'une session H (quota, pause/resume/send_message, suivi des événements)."""

import asyncio
import json
import time

from hai_agents import Client
from hai_agents.core.api_error import ApiError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage

TERMINAL = {"completed", "failed", "timed_out", "interrupted"}

READ_ONLY_TASK = (
    "Va sur https://fr.wikipedia.org et ouvre l'article 'Marathon de Paris'. Pour chacune des editions "
    "de 2015 a 2026, ouvre une par une la page Wikipedia du vainqueur hommes et releve sa nationalite et "
    "sa date de naissance, puis donne un tableau final. Lecture seule : ne remplis aucun formulaire, "
    "ne te connecte a rien, ne cree aucun compte."
)


def _strip_images(obj):
    if isinstance(obj, dict):
        return {k: _strip_images(v) for k, v in obj.items() if k not in ("image", "images", "screenshot")}
    if isinstance(obj, list):
        return [_strip_images(v) for v in obj]
    return obj


def _blob(data) -> str:
    return json.dumps(_strip_images(data), ensure_ascii=False)[:4000]


class HControl:
    def __init__(self, log=print) -> None:
        self.client = Client()
        self.s = self.client.sessions
        self.session_id: str | None = None
        self.events: list[dict] = []
        self.log = log
        self._follower: asyncio.Task | None = None
        self._next_index = 0

    async def wait_quota(self, max_wait_s: int = 600, every_s: int = 60) -> dict:
        start = time.monotonic()
        while True:
            q = await asyncio.to_thread(self.s.get_session_quota)
            self.log(f"[H] quota: limit={q.limit} active={q.active} available={q.available}")
            if q.available > 0:
                return {"limit": q.limit, "active": q.active, "available": q.available,
                        "waited_s": round(time.monotonic() - start, 1)}
            if time.monotonic() - start > max_wait_s:
                raise RuntimeError("Quota H a 0 pendant 10 min")
            await asyncio.sleep(every_s)

    async def create(self, task: str = READ_ONLY_TASK, agent: str = "h/web-surfer-pro") -> str:
        sess = await asyncio.to_thread(
            self.s.create_session, agent=agent, messages=task, max_steps=60,
            max_time_s=900, queue=False, delete_after_min=1440,
        )
        self.session_id = sess.id
        self.log(f"[H] session creee {sess.id} {sess.agent_view_url}")
        self._follower = asyncio.create_task(self._follow())
        return sess.id

    async def status(self) -> tuple[str, int | None]:
        st = await asyncio.to_thread(self.s.get_session_status, self.session_id)
        return str(st.status), st.steps

    async def wait_status(self, targets: set[str], timeout_s: float = 60, every_s: float = 0.2):
        """Renvoie (statut, secondes, nb de polls) des que le statut est dans targets (ou terminal)."""
        t0 = time.monotonic()
        polls = 0
        while time.monotonic() - t0 < timeout_s:
            st, _ = await self.status()
            polls += 1
            if st in targets or st in TERMINAL or st == "idle":
                return st, time.monotonic() - t0, polls
            await asyncio.sleep(every_s)
        return None, time.monotonic() - t0, polls

    async def pause(self) -> float:
        t0 = time.monotonic()
        await asyncio.to_thread(self.s.pause_session, self.session_id)
        return time.monotonic() - t0

    async def resume(self) -> float:
        t0 = time.monotonic()
        await asyncio.to_thread(self.s.resume_session, self.session_id)
        return time.monotonic() - t0

    async def send_message(self, text: str) -> float:
        t0 = time.monotonic()
        await asyncio.to_thread(self.s.send_session_messages, self.session_id, request=SendSessionMessagesRequestBody_UserMessage(
            type="user_message", message=text))
        return time.monotonic() - t0

    async def _follow(self) -> None:
        while self.session_id:
            try:
                ch = await asyncio.to_thread(
                    self.s.get_session_changes, self.session_id, from_index=self._next_index,
                    include_events=True, wait_for_seconds=20,
                )
            except ApiError as e:
                self.log(f"[H] changes erreur {e.status_code}")
                await asyncio.sleep(2)
                continue
            except Exception as e:  # noqa: BLE001
                self.log(f"[H] changes erreur {type(e).__name__}")
                await asyncio.sleep(2)
                continue
            recv = time.monotonic()
            if ch is None:
                continue
            evs = ch.new_events or []
            first = ch.first_index if ch.first_index is not None else self._next_index
            for i, ev in enumerate(evs):
                dumped = ev.model_dump(mode="json")
                data = dumped.get("data") or {}
                self.events.append({"index": first + i, "recv": recv, "type": dumped.get("type"),
                                    "kind": data.get("kind") if isinstance(data, dict) else None,
                                    "blob": _blob(data)})
            self._next_index = first + len(evs)
            if str(ch.status) in {"completed", "failed", "timed_out", "interrupted"} and not evs:
                return

    def find_event_after(self, t: float, needle: str | None = None, kinds: set[str] | None = None):
        for ev in self.events:
            if ev["recv"] < t:
                continue
            if kinds and ev["kind"] not in kinds and ev["type"] not in kinds:
                continue
            if needle and needle.lower() not in ev["blob"].lower():
                continue
            return ev
        return None

    async def cancel(self) -> None:
        sid, self.session_id = self.session_id, None
        if self._follower:
            self._follower.cancel()
        if not sid:
            return
        try:
            await asyncio.to_thread(self.s.cancel_session, sid)
            self.log(f"[H] session {sid} annulee")
        except ApiError as e:
            self.log(f"[H] cancel {sid} -> HTTP {e.status_code} (deja terminee ?)")
