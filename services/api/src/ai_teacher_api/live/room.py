"""A live class room: ONE teacher (a Gemini Live session) broadcast to N children. Pure room logic, no network code: members, the hand-raise queue and who holds the floor.

Rules (all in code, not in the prompt):
- Everyone hears the teacher and sees the board. Only the child who holds the FLOOR is heard by the teacher (their microphone / typed text is forwarded; everybody else is muted).
- A child raises a hand and joins the queue. When the teacher finishes a turn, the floor goes to the first child in the queue (the host can also give it at once).
- A room with a single child has no queue: the floor is always theirs.
- A floor that is not used within FLOOR_TIMEOUT seconds goes to the next child.
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

from ai_teacher_api.common import logsetup

log = logsetup.get("live")

FLOOR_TIMEOUT = 25.0
MAX_MEMBERS = 40
MAX_ROOMS = 5
ROOM_MINUTES = 30


@dataclass
class Member:
    id: str
    name: str
    send: object  # async callable(dict) -> None ; binary audio goes through send_bytes
    send_bytes: object
    is_host: bool = False


@dataclass
class Room:
    code: str
    host_key: str
    lesson_id: str = ""
    owner: str = ""  # the signed-in host who pays for this class (empty = local development without sign-in)
    in_audio_s: float = 0.0  # seconds of children's microphone audio sent to the teacher (billing)
    out_audio_s: float = 0.0  # seconds of the teacher's speech (billing)
    created: float = field(default_factory=time.time)
    started: bool = False
    members: dict[str, Member] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)  # member ids with a raised hand, in order
    floor: str | None = None
    floor_since: float = 0.0
    last_question: str = ""  # the question the teacher left open at the end of her last turn ("" = none): the next answer is checked against it
    discard: bool = False  # the child barged in: drop the rest of the teacher's current turn
    heard: str = ""  # what the floor holder said since the teacher's last turn (transcript of their voice, or typed text): the answer check reads it
    finished: bool = False  # the class is over (recap + home activity done): free conversation, no more steps
    picture_caps: dict = field(default_factory=dict)  # lesson picture name -> caption, for the board assistant
    notes: str = ""  # class notes / lesson text the answer judge checks against
    talk_started: float = 0.0  # when the last 'speak' press began (a lost 'done' message must not block the class for ever)
    talking: set = field(default_factory=set)  # children who pressed "speak": ONLY their microphone is heard (push-to-talk: background noise and side talk never reach the teacher)
    figures: dict = field(default_factory=dict)  # HTML figures made in the planning stage: name -> {html, caption, step} (show_figure)
    live_pictures: dict = field(default_factory=dict)  # picture name -> src of the running class (same dict as the teacher Turn's)
    last_question: dict | None = None  # the question closed last (answered, or hinted at): check_answer falls back to it
    catalog: dict = field(default_factory=dict)  # picture name -> {"caption"} (captions shown under pictures)
    open_question: dict | None = None  # {"q", "expected", "hinted"}: set while the class waits for a child (the wait_for_answer tool, or a question she asked without calling it)
    waiting: dict | None = None  # {"audio", "text", "event", "skip"}: wait_for_answer is running; the child's microphone is collected here instead of being sent to the speech model
    play_end: float = 0.0  # when the children have heard everything the teacher has said so far (the wait for an answer starts from here)
    owes_answer: float = 0.0  # when a child last spoke or typed something she has not yet answered ALOUD (0 = nothing is owed): a turn of only tool calls does not settle it
    ready_new: dict = field(default_factory=dict)  # visuals she asked for DURING the class that are ready and not yet shown: name -> times she was reminded
    answer_nudges: int = 0  # how many times in a row she was told to answer aloud
    _last_view: dict = field(default_factory=dict)
    figs_drawn: int = 0  # figures written DURING the class (the rare fallback tool draw_html)
    used: set = field(default_factory=set)  # names of prepared pictures / figures the teacher has shown so far
    drawn: int = 0  # pictures drawn DURING the class (the rare fallback tool draw_picture)
    last_child_audio: float = 0.0  # last time a child was actually heard speaking (transcript arrived / typed), NOT the last microphone chunk  # a child who pressed "I want to speak" while the teacher talks: their microphone is heard until the teacher's turn ends
    teacher_busy: bool = False  # the teacher is speaking / working: the floor is only given when the turn ends
    plan: list[str] = field(default_factory=list)
    topic_text: str = ""
    task: asyncio.Task | None = None
    closer: asyncio.Task | None = None  # pending "close the empty room" task
    live: object = None  # the Gemini Live session while connected
    board: list = field(default_factory=list)  # elements on the board now (shared with the tools' Turn)

    def board_status(self, pictures: dict[str, str]) -> str:
        """What the teacher is told about the screen (live/boardstate.py)."""
        from ai_teacher_api.live import boardstate
        return boardstate.describe(self.board, pictures, self.figures, self.used)

    # ------------------------------------------------------------ state log
    def state_view(self) -> dict:
        screen = [(e.get("name") or e.get("text") or e.get("type", ""))[:18] for e in self.board]
        return {"busy": self.teacher_busy, "talking": sorted(self.talking), "floor": self.floor, "queue": len(self.queue), "question": (self.open_question or {}).get("q", "")[:50],
                "waiting": bool(self.waiting), "finished": self.finished, "screen": screen}

    def log_state(self, why: str, **extra) -> None:
        """One log line for every change of the class state, with the reason: what changed [old, new] and why. Read logs/live.jsonl with `event == "state"` to follow a class."""
        now, old = self.state_view(), self._last_view
        changed = {k: [old.get(k), v] for k, v in now.items() if old.get(k) != v}
        self._last_view = now
        if changed or extra:
            log.info("state", room=self.code, why=why, changed=changed, **extra)

    # ------------------------------------------------------------ members
    def add(self, m: Member) -> None:
        self.members[m.id] = m

    def remove(self, mid: str) -> None:
        self.members.pop(mid, None)
        if mid in self.queue:
            self.queue.remove(mid)
        if self.floor == mid:
            self.floor = None
        self.talking.discard(mid)

    def children(self) -> list[Member]:
        return list(self.members.values())

    def solo(self) -> bool:
        return len(self.members) == 1

    # ------------------------------------------------------------ hands and floor
    def raise_hand(self, mid: str) -> None:
        if mid in self.members and mid not in self.queue and self.floor != mid:
            self.queue.append(mid)

    def lower_hand(self, mid: str) -> None:
        if mid in self.queue:
            self.queue.remove(mid)

    def grant_next(self) -> str | None:
        """Give the floor to the first child in the queue (or keep an open floor in a solo room). Returns the new holder."""
        self.floor = None
        while self.queue:
            mid = self.queue.pop(0)
            if mid in self.members:
                self.floor = mid
                break
        if self.floor is None and self.solo():
            self.floor = next(iter(self.members))
        self.floor_since = time.time()
        return self.floor

    def release_floor(self, mid: str) -> bool:
        if self.floor == mid:
            self.floor = None
            return True
        return False

    def may_speak(self, mid: str) -> bool:
        return self.floor == mid or (self.solo() and mid in self.members)

    def mic_open(self, mid: str) -> bool:
        """Is this child's microphone heard NOW? Only after the child pressed "speak" (and holds the floor). An always-open microphone also hears the loudspeaker echo, the room and people talking
        nearby, and the teacher then answers things nobody asked her (seen 2026-10-15: 'नहीं, नहीं, नहीं, प्रियंका' from the room was taken as the child's answer)."""
        return self.may_speak(mid) and mid in self.talking

    def floor_expired(self) -> bool:
        return self.floor is not None and not self.solo() and time.time() - self.floor_since > FLOOR_TIMEOUT

    # ------------------------------------------------------------ views
    def public_state(self) -> dict:
        names = {m.id: m.name for m in self.members.values()}
        return {"type": "state", "code": self.code, "started": self.started, "members": [{"id": m.id, "name": m.name, "host": m.is_host} for m in self.members.values()],
                "queue": [{"id": i, "name": names[i]} for i in self.queue if i in names], "floor": self.floor, "floor_name": names.get(self.floor or "", ""),
                "teacher_busy": self.teacher_busy, "plan": self.plan, "finished": self.finished}

    def snapshot(self) -> dict:
        """What a child who joins late needs to see: state + the board as it is now."""
        return {**self.public_state(), "board": list(self.board)}

    def expired(self) -> bool:
        return time.time() - self.created > ROOM_MINUTES * 60

    async def broadcast(self, event: dict) -> None:
        for m in list(self.members.values()):
            try:
                await m.send(event)
            except Exception:  # noqa: BLE001 - a dead connection is removed by its own handler
                pass

    async def broadcast_bytes(self, data: bytes) -> None:
        for m in list(self.members.values()):
            try:
                await m.send_bytes(data)
            except Exception:  # noqa: BLE001
                pass


ROOMS: dict[str, Room] = {}


def new_room(lesson_id: str = "", owner: str = "") -> Room:
    for c in [c for c, r in ROOMS.items() if r.expired() and not r.members]:
        ROOMS.pop(c)
    if len(ROOMS) >= MAX_ROOMS:
        raise RuntimeError("too many live classes are running; try again later")
    code = "".join(secrets.choice("0123456789") for _ in range(5))
    while code in ROOMS:
        code = "".join(secrets.choice("0123456789") for _ in range(5))
    r = Room(code=code, host_key=secrets.token_urlsafe(12), lesson_id=lesson_id, owner=owner)
    ROOMS[code] = r
    return r
