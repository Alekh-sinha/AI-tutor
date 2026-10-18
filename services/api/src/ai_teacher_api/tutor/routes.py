"""Student-facing teacher, two modes streamed as server-sent events:
- `chat`: plain ChatGPT-style chat (text/voice/photo in, text [+ voice] out, at most a picture or two). See chat.py.
- `teach`: live class on a recorded lesson, or on ANY topic the child asks for (the teacher prepares for a while first, see prep.py), then teaches step by step on a whiteboard.
Logs: logs/tutor.jsonl (one `turn` event per request with inputs, tool counts, duration, errors; plus one event per spoken sentence / board action / picture)."""

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.adk.agents import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.access import auth, library
from ai_teacher_api.common import logsetup, sse
from ai_teacher_api.common.paths import DATA_DIR, split_public_id
from ai_teacher_api.common.settings import DEFAULT_VOICE, WEB_PUBLIC
from ai_teacher_api.content.brief import LessonBrief, render
from ai_teacher_api.safety import gate
from ai_teacher_api.tutor import agent as tutor
from ai_teacher_api.tutor import chat as plain_chat
from ai_teacher_api.tutor import prep

log = logsetup.get("tutor")
router = APIRouter()

MAX_TURNS = {"chat": 30, "teach": 40}  # cost caps per session; a session is one sitting
MAX_TEXT, MAX_IMAGE_B64, MAX_AUDIO_B64 = 600, 2_000_000, 1_500_000
_sessions = InMemorySessionService()
_runner = Runner(agent=tutor.build_tutor(), app_name="ai-teacher-chat", session_service=_sessions)
_chat_runner = Runner(agent=plain_chat.build_chat_agent(), app_name="ai-teacher-chat", session_service=_sessions)
_state: dict[str, dict] = {}  # session id -> {"turns": int, "board": [...]}

THINKING_LABELS = {"plan": "योजना बना रहा हूँ…", "say": "", "write_on_board": "बोर्ड पर लिख रहा हूँ…", "show_lesson_picture": "चित्र ढूँढ रहा हूँ…",
                   "draw_picture": "चित्र बना रहा हूँ…", "clear_board": ""}


class ChatIn(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{6,64}$")
    lesson_id: str = Field("", pattern=r"^[A-Za-z0-9_-]{0,40}$", description="the recorded lesson being watched; empty = no lesson (free chat, or a live class on the child's own topic)")
    mode: str = Field("chat", pattern="^(chat|teach)$")
    voice_reply: bool = Field(False, description="chat: also speak the answer (always done when the child spoke)")
    t: float = 0
    text: str = ""
    image_b64: str | None = None
    image_mime: str = "image/jpeg"
    audio_b64: str | None = None
    audio_mime: str = "audio/wav"
    voice: str = DEFAULT_VOICE
    interrupted_after: str = Field("", max_length=400, description="live class: the last sentence the child heard before interrupting")


def _lesson(lesson_id: str) -> dict | None:
    if not lesson_id:
        return None
    f = WEB_PUBLIC / "lessons" / f"{lesson_id}.json"
    if not f.exists():
        raise HTTPException(404, "unknown lesson")
    return json.loads(f.read_text())


async def _run_turn(body: ChatIn, turn: tutor.Turn, parts: list[types.Part], kinds: list[str], prep_parts: list[types.Part] | None = None) -> None:
    tutor.CURRENT.set(turn)
    q, t0, tools = turn.queue, time.time(), {}
    err = ""
    plain = body.mode == "chat"
    try:
        if prep_parts is not None:  # live class on the child's own topic: prepare first (takes a while), then teach
            q.put_nowait({"type": "thinking", "text": "टीचर क्लास की तैयारी कर रही हैं… (थोड़ा समय लगेगा)"})
            r = await prep.prepare(prep_parts, prep.recorded_lessons(), None, body.session_id)
            if r["refused"]:
                await tutor.say(r["refused"])
                return
            turn.lesson_pictures.update(prep.pictures_of(r["related"]))  # same dict as the session's: later turns keep them
            parts[0] = types.Part(text=parts[0].text.replace("{PREP}", r["notes"]).replace("{PICTURES}", "; ".join(turn.lesson_pictures) or "(none)"))
            q.put_nowait({"type": "thinking", "text": "क्लास शुरू हो रही है…"})
        msg = types.Content(role="user", parts=parts)
        final = ""
        async for e in (_chat_runner if plain else _runner).run_async(user_id="student", session_id=body.session_id, new_message=msg, run_config=RunConfig(max_llm_calls=25)):
            for c in e.get_function_calls():
                tools[c.name] = tools.get(c.name, 0) + 1
                label = THINKING_LABELS.get(c.name, "")
                if label:
                    q.put_nowait({"type": "thinking", "text": label})
            for p in (e.content.parts if e.content else []):
                if p.thought and p.text:
                    q.put_nowait({"type": "thought", "text": p.text.strip()[:600]})  # English summary: shown only in the debug view
                elif p.text and e.is_final_response() and not e.get_function_calls():
                    if plain:
                        final += p.text
                    elif turn.said == 0:
                        log.warn("plain-text-answer", session=body.session_id, text=p.text[:200])
                        await tutor.say(p.text)  # the model answered in plain text instead of `say`: still speak it
        if plain and final.strip():
            audio = None
            if body.voice_reply or "audio" in kinds:
                q.put_nowait({"type": "thinking", "text": "आवाज़ बना रहा हूँ…"})
                audio = await plain_chat.speak(final, body.voice, body.session_id)
            q.put_nowait({"type": "text", "text": final.strip(), "audio": audio})
    except Exception as ex:  # noqa: BLE001
        err = repr(ex)[:400]
        log.error("turn-failed", session=body.session_id, error=err)
        q.put_nowait({"type": "error", "text": "कुछ गड़बड़ हो गई, फिर से पूछिए।", "detail": err[:200]})
    finally:
        log.info("turn", session=body.session_id, lesson=body.lesson_id, mode=body.mode, inputs=kinds, question=body.text[:200], tools=tools,
                 said=turn.said, new_pictures=turn.new_pictures, seconds=round(time.time() - t0, 1), error=err)
        q.put_nowait({"type": "done"})


@router.post("/chat")
async def chat(body: ChatIn, u: dict = Depends(auth.active_user)) -> StreamingResponse:
    if len(body.text) > MAX_TEXT or len(body.image_b64 or "") > MAX_IMAGE_B64 or len(body.audio_b64 or "") > MAX_AUDIO_B64:
        raise HTTPException(413, "message too large")
    if not (body.text.strip() or body.image_b64 or body.audio_b64):
        raise HTTPException(400, "empty message")
    if body.lesson_id and not library.can_see(body.lesson_id, u):
        raise HTTPException(403, "this lesson is not shared with you")
    lesson = _lesson(body.lesson_id)
    media = ([tutor.blob_part(body.image_b64, body.image_mime)] if body.image_b64 else []) + ([tutor.blob_part(body.audio_b64, body.audio_mime)] if body.audio_b64 else [])
    verdict = await gate.screen(body.text, "student", media)  # safety gate: refused / distress messages never reach the teacher agent
    if not verdict.ok:
        say = verdict.message_hi

        async def blocked():
            for ev in ({"type": "text", "text": say, "audio": None, "safety": verdict.decision}, {"type": "done"}):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

        return StreamingResponse(blocked(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    st = _state.setdefault(body.session_id, {"turns": 0, "board": [], "pictures": {}})
    if st["turns"] >= MAX_TURNS[body.mode]:
        log.warn("session-limit", session=body.session_id, mode=body.mode)
        raise HTTPException(429, "session limit reached")
    first = st["turns"] == 0
    st["turns"] += 1
    if first:
        await _sessions.create_session(app_name="ai-teacher-chat", user_id="student", session_id=body.session_id)
    prep_parts = None
    if lesson:
        context, pics = tutor.lesson_context(lesson, body.t, prep.book_points(body.lesson_id), st["board"], live=body.mode == "teach")
    elif body.mode == "teach" and first:  # the child's own topic: the class notes are filled in by the turn after preparing
        context, pics = ("PREPARED CLASS NOTES (written by you, for this child's topic; teach in your own live words, do not read them):\n{PREP}\n\nPICTURES you may show (name: caption): {PICTURES}\n\n"
                         f"ON THE BOARD NOW: {st['board'] or 'empty'}"), st["pictures"]
        prep_parts = []
    elif body.mode == "teach":
        context, pics = "", st["pictures"]
    else:
        context, pics = f"No lesson is open: this is a free question about the child's studies.\nON THE BOARD NOW: nothing (plain chat).", {}
    head = context if first else (f"ON THE BOARD NOW: {st['board'] or 'empty'}" if body.mode == "teach" else "")
    if lesson and body.mode != "teach" and not first:
        head = tutor.position_note(lesson, body.t)
    if body.mode == "teach" and first:
        head += "\n\n" + (tutor.LIVE_START if lesson else tutor.LIVE_START_TOPIC)
    if body.interrupted_after:
        head += f"\n\nThe child interrupted you after you said: \"{body.interrupted_after}\". Answer first, then offer to continue."
    ask = f"\n\nCHILD'S MESSAGE: {body.text}" if body.text.strip() else "\n\nThe child's message is in the attachment."
    if verdict.decision == "sensitive":
        ask += "\n\n(SAFETY NOTE: a sensitive school topic. Answer at NCERT textbook level: calm, scientific words, no sexual detail, symbolic diagrams only; if it is a private matter, suggest asking a parent or trusted teacher.)"
    parts, kinds = [types.Part(text=head + ask)], ["text"] if body.text.strip() else []
    if body.image_b64:
        parts.append(tutor.blob_part(body.image_b64, body.image_mime))
        kinds.append("image")
    if body.audio_b64:
        parts.append(tutor.blob_part(body.audio_b64, body.audio_mime))
        kinds.append("audio")
    turn = tutor.Turn(queue=asyncio.Queue(), session_id=body.session_id, lesson_pictures=pics, board=st["board"], voice=body.voice)
    if prep_parts is not None:
        prep_parts = [types.Part(text="The child wants to learn this:" + (f" {body.text.strip()}" if body.text.strip() else "")), *parts[1:]]
    task = asyncio.create_task(_run_turn(body, turn, parts, kinds, prep_parts))

    async def stream():
        try:
            async for chunk in sse.events(turn.queue, 400):
                yield chunk
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
