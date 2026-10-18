"""The student's doubt-chat teacher: one ADK agent that hears (text, a voice recording, a photo), thinks, and answers like a teacher at a whiteboard:
it writes on the board, shows pictures, draws new ones, and speaks. The UI replays everything it does in order, so the board changes while the voice talks.

The agent never sends plain text to the child: everything the child hears goes through `say`, everything seen through the board tools. Each tool pushes an
event into the current turn's queue (ContextVar), which the API streams to the browser (server-sent events).
"""

import asyncio
import base64
import contextvars
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.genai import types

from ai_teacher_api.safety import policy
from ai_teacher_api.common import logsetup, workspace
from ai_teacher_api.common.settings import WEB_PUBLIC, retrying_model
from ai_teacher_api.authoring import illustrator as ill

log = logsetup.get("tutor")
MAX_SAY_CHARS = 400
MAX_NEW_PICTURES_PER_TURN = 2


@dataclass
class Turn:
    """What a running turn needs: where to push events, which lesson pictures it may show, and its limits."""

    queue: asyncio.Queue
    session_id: str
    lesson_pictures: dict[str, str] = field(default_factory=dict)  # name -> /img/... url
    board: list[dict] = field(default_factory=list)  # elements on the board right now (persisted by the API between turns)
    new_pictures: int = 0
    said: int = 0
    waiting: bool = False  # the teacher asked the child a question: nothing more may be said this turn
    counter: int = 0
    voice: str = "Zephyr"
    extra: dict = field(default_factory=dict)  # live class: the Room (answer checks, finish_class)
    max_notes: int = 5  # the board never scrolls: beyond this the oldest note fades out
    max_visuals: int = 99  # pictures + figures on the board at once (live class: 2)
    say_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # parallel `say` calls must run one at a time, in order


CURRENT: contextvars.ContextVar[Turn] = contextvars.ContextVar("turn")


META: contextvars.ContextVar[dict] = contextvars.ContextVar("meta", default={})  # extra fields merged into every pushed event (live class: which turn / character the event belongs to)


def _push(event: dict) -> None:
    CURRENT.get().queue.put_nowait({**event, **META.get()})


def _new_id(prefix: str) -> str:
    t = CURRENT.get()
    t.counter += 1
    return f"{prefix}{int(time.time()) % 100000}-{t.counter}"


# ---------------------------------------------------------------- tools
async def plan(steps: list[str]) -> dict:
    """Show the child (in Hindi, very short) how you will answer: 2-4 steps. Call this FIRST for any question that needs more than one sentence.

    Args:
        steps: the steps of your answer, e.g. ["पहले देखेंगे कि लकड़ी क्या है", "फिर चित्र से समझेंगे", "आख़िर में एक सवाल"].
    """
    _push({"type": "plan", "steps": steps[:5]})
    log.info("plan", session=CURRENT.get().session_id, steps=steps[:5])
    return {"status": "ok"}


async def say(text: str) -> dict:
    """Speak to the child in Hindi: one or two short sentences, warm and simple (about 8-30 words). The child hears it and sees it as a caption.
    Use several short `say` calls, interleaved with the board tools, as a teacher talks while writing.

    Args:
        text: what you say aloud, in simple Hindi.
    """
    text = text.strip()[:MAX_SAY_CHARS]
    if not text:
        return {"status": "error", "error": "empty"}
    from ai_teacher_api.common.tts import synth_retry, to_mp3  # local import: Cloud TTS client is only needed when speaking

    turn = CURRENT.get()
    async with turn.say_lock:  # the model may call `say` several times in ONE response: the check below must see the earlier calls
        if turn.waiting:
            return {"status": "error", "error": "you already asked the child a question: say nothing more, finish your turn and wait for the answer"}
        turn.waiting = text.rstrip().endswith(("?", "？"))
        audio = None
        try:
            pcm = await synth_retry(_tts_client(), text, turn.voice, "hi-IN", 1.0)
            audio = base64.b64encode(to_mp3(pcm)).decode()
        except Exception as e:  # noqa: BLE001 - the caption still shows if the voice fails
            log.error("tts-failed", session=turn.session_id, error=repr(e)[:200])
        turn.said += 1
        log.info("say", session=turn.session_id, text=text, tts_ok=audio is not None)
        _push({"type": "say", "text": text, "audio": audio})
    return {"status": "ok"}


_client = None


def _tts_client():
    global _client
    if _client is None:
        from google.cloud import texttospeech as gt

        _client = gt.TextToSpeechClient()
    return _client


async def write_on_board(text: str, style: str = "body") -> dict:
    """Write a short note on the whiteboard (at most 8 words: a key term, a fact, a step). The board holds about 5 short lines; older notes go when it is full.

    Args:
        text: the words to write, in Hindi (an emoji is welcome).
        style: "heading", "body", "bullet" or "key" (a highlighted key term or answer).
    """
    style = style if style in ("heading", "body", "bullet", "key") else "body"
    el = {"type": "note", "id": _new_id("n"), "text": text.strip()[:80], "style": style}
    _board(el)
    _push({"type": "board", "op": "add", "el": el})
    log.info("board-note", session=CURRENT.get().session_id, text=el["text"], style=style)
    return {"status": "ok", "id": el["id"]}


async def show_lesson_picture(name: str, caption: str = "") -> dict:
    """Put one of the lesson's own pictures on the board (the list of names is in the message). Use this first; it is instant.

    Args:
        name: a picture name from the lesson's list.
        caption: at most 4 Hindi words naming what it shows.
    """
    t = CURRENT.get()
    if name not in t.lesson_pictures:
        return {"status": "error", "error": f"no such lesson picture; choose from {sorted(t.lesson_pictures)}"}
    el = {"type": "image", "id": _new_id("i"), "src": t.lesson_pictures[name], "caption": caption.strip()[:40]}
    _board(el)
    _push({"type": "board", "op": "add", "el": el})
    return {"status": "ok", "id": el["id"]}


async def draw_picture(description: str, caption: str = "") -> dict:
    """Draw a NEW realistic photograph for the board when none of the lesson's pictures fits (slow: up to a minute; at most two per answer). You get it back to check.

    This image model draws still, simple scenes well (one or two objects, materials side by side, a person doing a simple thing). It draws badly: motion, things
    collapsing or pouring, exact counts, tiny parts, anything needing text. Describe a single still moment.

    Args:
        description: concrete English description of the photo (who/what, where, close-up or wide). Never ask for writing in it.
        caption: at most 4 Hindi words naming what it shows.
    """
    t = CURRENT.get()
    if t.new_pictures >= MAX_NEW_PICTURES_PER_TURN:
        return {"status": "error", "error": "you already drew the most pictures allowed for one answer; explain in words or reuse a lesson picture"}
    t.new_pictures += 1
    if not workspace.try_acquire(f"tutor picture {t.session_id}"):
        log.warn("draw-busy", session=t.session_id, holder=workspace.holder["who"])
        return {"status": "error", "error": "the picture tools are busy right now: explain in words or use a lesson picture"}
    _push({"type": "thinking", "text": "चित्र बना रहा हूँ…"})
    name = _new_id("p")
    out_dir = WEB_PUBLIC / "chat" / re.sub(r"[^A-Za-z0-9_-]", "", t.session_id)
    ill.configure(out_dir, ill.IMAGE_MODEL)
    ill.set_redraw_allowed(None)
    ill.set_budget(3)
    try:
        res = await asyncio.to_thread(ill.generate_image, name, description)
    finally:
        workspace.release()
    log.info("draw-picture", session=t.session_id, description=description[:300], status=res.get("status"), error=res.get("error", ""))
    if res.get("status") != "ok":
        return res
    el = {"type": "image", "id": name, "src": f"/chat/{out_dir.name}/{name}.webp", "caption": caption.strip()[:40]}
    _board(el)
    _push({"type": "board", "op": "add", "el": el})
    return {"status": "ok", "id": name, "photo": res["photo"]}  # returned so you can look at it


async def clear_board() -> dict:
    """Wipe the board (when you start a new idea)."""
    CURRENT.get().board.clear()
    _push({"type": "board", "op": "clear"})
    return {"status": "ok"}


def _board(el: dict) -> None:
    t = CURRENT.get()
    board = t.board
    board.append(el)
    for kind, limit in (("notes", t.max_notes), ("visuals", t.max_visuals)):
        pick = (lambda e: e["type"] == "note" and e.get("style") != "pending") if kind == "notes" else (lambda e: e["type"] in ("image", "figure") or e.get("style") == "pending")
        items = [e for e in board if pick(e)]
        while len(items) > limit:  # the board never scrolls: the oldest item fades out
            old = items.pop(0)
            board.remove(old)
            _push({"type": "board", "op": "hide", "id": old["id"]})


# ---------------------------------------------------------------- the agent
INSTRUCTION = """You are the class teacher answering a Class 6 child's doubt (11-12 years, Hindi-medium school, rural Bihar), often alone on a phone with nobody to ask. Be warm, patient and
brief, like a good teacher at the blackboard, speaking simple Hindi. The child may write, speak, or send a photo (of a page, an object, a drawing): look at it and answer what they ask.

How you work:
- The child hears and sees ONLY what you do through your tools: `say` (speech and caption), `write_on_board`, `show_lesson_picture`, `draw_picture`, `clear_board`. Plain text is not delivered.
- For anything longer than one sentence, call `plan` first with 2-4 short steps, then act: say a sentence, write the key word on the board, show a picture, say the next sentence.
  Talk and board together, as a teacher does. Prefer the lesson's own pictures; draw a new one only when none fits.
- First understand what the child really asks, and what they already know from the lesson (the lesson and the board are in the message). Explain from something they know and see,
  one step at a time. Finish by checking understanding with one small question when it fits.
- Facts come from the BOOK POINTS in the message and ordinary school-level knowledge you are sure of. If you are not sure, say so honestly ("मुझे पक्का नहीं पता, अपने शिक्षक से पूछिए"); never guess.
- Stay with the child's studies and this lesson. For anything else (personal details, unsafe or adult topics, chat), kindly bring them back; never ask for personal information.
- Never mock a wrong idea; say what is right in it, then fix it. Short answers: usually 3-6 `say` calls in all. If you ask the child a question, STOP right after asking it: the child answers in the next message; never answer your own question."""
INSTRUCTION += "\n\n" + policy.POLICY


LIVE_START = """START THE LIVE CLASS now. You are leading this class on the lesson's topic, not answering a question. First `plan` the class (3-5 steps, one per concept of the BOOK POINTS).
Then teach ONE step per turn: connect to something the child knows, say it in short sentences, write the key words, show a picture, and end the step by asking ONE check question to the
child and stopping (the child answers, or presses 'continue'). When the child answers, say briefly what is right and what is not, then go on to the next step. If they interrupt with a
doubt, answer it first. At the end give a short recap and the home activity."""


LIVE_START_TOPIC = """START THE LIVE CLASS now. The child asked to learn the topic described in the PREPARED CLASS NOTES, which no recorded lesson covers fully. Welcome them in one short sentence, then
`plan` the class from the STEPS (3-5 steps) and teach ONE step per turn as described: connect to something the child knows, write key words, show a picture when one fits (draw a new one only if it
truly helps), and end the step with ONE check question, then stop. Check the PREREQUISITES with a first small question if unsure. When the child answers, say briefly what is right and what is not, then go on.
If they interrupt with a doubt, answer it first. At the end give a short recap."""


def build_tutor(model: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="tutor",
        model=retrying_model(model),
        instruction=INSTRUCTION,
        tools=[plan, say, write_on_board, show_lesson_picture, draw_picture, clear_board],
        planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)),
    )


def lesson_context(lesson: dict, t: float, book_points: str, board: list[dict], live: bool = False) -> tuple[str, dict[str, str]]:
    """Text the tutor needs about the lesson: what was taught so far, what is ahead, the pictures it may show, the board now."""
    done = [n["text"] for n in lesson["narration"] if n["end"] <= t]
    ahead = [n["text"] for n in lesson["narration"] if n["end"] > t]
    pics = {e["id"]: e["src"] for e in lesson["events"] if e["type"] == "image" and "~" not in e["id"]}  # `name~q` = the same picture shown again
    caps = {k: next((e.get("caption") or "" for e in lesson["events"] if e.get("id") == k), "") for k in pics}
    text = (
        f"LESSON: {lesson['title']}\n\nBOOK POINTS (authority):\n{book_points or '(none)'}\n\n"
        + ("THE RECORDED LESSON ON THIS TOPIC (for your reference; teach in your own live words, do not read it):\n" + "\n".join(n["text"] for n in lesson["narration"])
           if live else "THE WHOLE LESSON, in order (what the teacher intends to teach in this video; use it to see what the child has been taught, what is still to come, and how the lesson explains each idea, "
           "so that your answer matches it and does not contradict it):\n" + "\n".join(n["text"] for n in lesson["narration"])
           + "\n\nWHAT THE TEACHER HAS TAUGHT SO FAR (up to where the child is now):\n" + "\n".join(done[-60:])
           + "\n\nWHAT COMES NEXT IN THE LESSON (the child has not heard it yet):\n" + "\n".join(ahead[:25]))
        + "\n\nLESSON PICTURES you may show (name: caption): " + "; ".join(f"{k}: {v}" for k, v in caps.items())
        + f"\n\nON THE BOARD NOW: {board or 'empty'}"
    )
    return text, pics


def position_note(lesson: dict, t: float) -> str:
    """Where the child is in the video right now, for every question (the full context is only sent with the first one, and the child may have watched on since)."""
    heard = [n["text"] for n in lesson["narration"] if n["end"] <= t][-3:]
    return "WHERE THE CHILD IS IN THE VIDEO NOW (the last lines they heard): " + (" / ".join(heard) if heard else "at the very start")


def blob_part(b64: str, mime: str) -> types.Part:
    return types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime)
