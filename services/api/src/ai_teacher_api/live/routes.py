"""Live class API. `POST /live/rooms` creates a room (a 5-digit class code + a host key); children join `WS /live/ws/{code}`; the host starts the class.

Client -> server (JSON text frames): hello{name} is implied by the query string; start{topic?} (host), continue (host), hand, lower, done (floor holder finished), text{text} (floor holder), grant (host: give the floor now).
Client -> server (binary frames): 16 kHz mono 16-bit PCM from the microphone (heard only when the sender holds the floor).
Server -> client (JSON): state, snapshot(on join), caption{delta}, caption_end, heard{name,delta}, interrupted, plan, board{op,el}, thinking{text}, error, ended. (binary): 24 kHz mono 16-bit PCM of the teacher's voice.
Logs: logs/live.jsonl (room, join, leave, start, hand, floor, tool, teacher-turn, interrupted, session-error ...)."""

import asyncio
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.access import auth, credits, usage
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_VOICE
from ai_teacher_api.live import prepare, prompt, session
from ai_teacher_api.live.room import MAX_MEMBERS, ROOMS, Member, Room, new_room
from ai_teacher_api.tutor import agent as tutor
from ai_teacher_api.tutor import prep

log = logsetup.get("live")
router = APIRouter(prefix="/live")
MAX_CHUNK = 64_000
MIN_CLASS_USD = 0.60  # balance needed to start a class
GRACE_SECONDS = 60  # an empty room stays this long, so a reload or a dropped connection can come back


class RoomIn(BaseModel):
    lesson_id: str = Field("", pattern=r"^[A-Za-z0-9_-]{0,40}$", description="a recorded lesson to teach, or empty: the children say what they want to learn")


@router.post("/rooms")
async def create_room(body: RoomIn, u: dict = Depends(auth.active_user)) -> dict:
    """The signed-in, approved host creates the class and pays for it; children join with the code and need no account."""
    await asyncio.to_thread(credits.check, u["email"])
    if u["role"] != "admin" and credits.balance_micro(u) < round(MIN_CLASS_USD * credits.M):
        raise credits.CreditExhausted()
    if body.lesson_id:
        try:
            prep.load_lesson(body.lesson_id)
        except FileNotFoundError:
            raise HTTPException(404, "unknown lesson") from None
    try:
        room = new_room(body.lesson_id, u["email"])
    except RuntimeError as e:
        raise HTTPException(429, str(e)) from e
    log.info("room-created", room=room.code, lesson=body.lesson_id)
    return {"code": room.code, "host_key": room.host_key, "lesson_id": room.lesson_id}


@router.get("/rooms/{code}")
def room_info(code: str) -> dict:
    r = ROOMS.get(code)
    if not r or r.expired():
        raise HTTPException(404, "no such class")
    return {"code": code, "started": r.started, "members": len(r.members), "lesson_id": r.lesson_id}


def _instruction_and_pictures(room: Room) -> tuple[str, dict[str, str]]:
    """Recorded lesson as the class: its text and its pictures."""
    context, pics = tutor.lesson_context(prep.load_lesson(room.lesson_id), 0, prep.book_points(room.lesson_id), [], live=True)
    return prompt.TEACHER + "\n\n" + context, pics


async def _progress(room: Room, text: str) -> None:
    await room.broadcast({"type": "thinking", "text": text})


async def _run(room: Room, topic: str) -> None:
    """Planning stage first (a topic class: notes + pictures, a few minutes, children see the progress), then the live session."""
    usage.set_user(room.owner or None)  # every model call of this class is charged to the host
    try:
        if room.lesson_id:
            instruction, pics = _instruction_and_pictures(room)
            first = prompt.START
        elif topic.strip():
            r = await prepare.prepare_topic(room.code, topic.strip()[:200], lambda t: _progress(room, t))
            if r.get("refused"):
                await room.broadcast({"type": "ended", "reason": r["refused"]})
                return
            room.figures = r["figures"]
            room.catalog = {k: {"caption": v["caption"]} for k, v in r["pictures"].items()}
            instruction = (prompt.TEACHER + "\n\n" + prompt.HAS_TOPIC + "\n\nCLASS NOTES:\n" + r["notes"] + "\n\nSUGGESTED STEPS: " + "; ".join(r["steps"]) + "\n\nCATALOG\n" + r["catalog"])
            pics = {k: v["src"] for k, v in r["pictures"].items()}
            first = f"आज बच्चे यह सीखना चाहते हैं: {topic.strip()[:200]}\n{prompt.START}"
        else:
            instruction, pics = prompt.TEACHER + "\n\n" + prompt.NO_TOPIC, {}
            first = prompt.START_NO_TOPIC
        await room.broadcast({"type": "thinking", "text": ""})
        log.info("start", room=room.code, lesson=room.lesson_id, topic=topic[:200], children=len(room.members), pictures=sorted(pics))
        room.live_pictures = pics
        await session.run_room(room, instruction, pics, DEFAULT_VOICE, f"{room.board_status(pics)}\n{first}")
    except asyncio.CancelledError:
        raise
    except credits.AccessDenied as e:
        log.warn("class-stopped-access", room=room.code, owner=room.owner, code=e.code)
        await room.broadcast({"type": "ended", "reason": e.hi, "code": e.code})
    except Exception as e:  # noqa: BLE001
        log.error("class-failed", room=room.code, error=repr(e)[:400])
        await room.broadcast({"type": "ended", "reason": "क्लास शुरू नहीं हो सकी। फिर से कोशिश कीजिए।"})


async def _start(room: Room, topic: str) -> None:
    room.started = True
    room.task = asyncio.create_task(_run(room, topic))
    await room.broadcast(room.public_state())


@router.websocket("/ws/{code}")
async def ws(websocket: WebSocket, code: str, name: str = "", key: str = "") -> None:
    room = ROOMS.get(code)
    if not room or room.expired() or len(room.members) >= MAX_MEMBERS:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    mid = secrets.token_hex(4)
    m = Member(id=mid, name=(name.strip()[:20] or f"बच्चा {len(room.members) + 1}"), send=websocket.send_json, send_bytes=websocket.send_bytes,
               is_host=bool(key) and secrets.compare_digest(key, room.host_key))
    if room.closer:
        room.closer.cancel()
        room.closer = None
    room.add(m)
    log.info("join", room=code, member=mid, name=m.name, host=m.is_host, members=len(room.members))
    await websocket.send_json({"type": "hello", "id": mid, "host": m.is_host, "lesson_id": room.lesson_id})
    await websocket.send_json(room.snapshot())
    await room.broadcast(room.public_state())
    audio_s = 0.0
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if room.live and room.mic_open(mid) and len(data) <= MAX_CHUNK:
                    audio_s += len(data) / 32000
                    room.in_audio_s += len(data) / 32000
                    await room.live.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
                continue
            ev = json.loads(msg["text"]) if msg.get("text") else {}
            t = ev.get("type")
            if t == "start" and m.is_host and not room.started:
                await _start(room, str(ev.get("topic", "")))
            elif t == "continue" and m.is_host and room.live:
                room.teacher_busy = True
                await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=f"{room.board_status(room.live_pictures)}\n{prompt.HOST_CONTINUE}")]), turn_complete=True)
            elif t == "hand":
                room.raise_hand(mid)
                log.info("hand", room=code, member=mid, name=m.name, queue=len(room.queue))
                if not room.teacher_busy and room.floor is None:
                    room.grant_next()
                await room.broadcast(room.public_state())
            elif t == "talk":  # push-to-talk: the child presses "speak" (stops the teacher at once) and "done" when finished
                if ev.get("on"):
                    if not room.may_speak(mid) and room.floor is None:  # hold-to-speak: when nobody holds the floor, pressing "speak" takes it (the hand-raise queue is not offered in the UI)
                        room.lower_hand(mid)
                        room.floor, room.floor_since = mid, time.time()
                        await room.broadcast(room.public_state())
                    if not room.may_speak(mid):
                        await websocket.send_json({"type": "busy"})  # somebody else is speaking: wait for them to finish
                    else:
                        room.talking.add(mid)
                        room.talk_started = time.time()
                        room.last_child_audio = time.time()
                        if room.teacher_busy:
                            room.discard = True  # what she still has queued is dropped at once
                            await room.broadcast({"type": "interrupted"})
                        log.info("talk", room=code, member=mid, teacher_was_talking=room.teacher_busy)
                else:
                    room.talking.discard(mid)
            elif t == "lower":
                room.lower_hand(mid)
                await room.broadcast(room.public_state())
            elif t == "grant" and m.is_host:
                if room.live:
                    await room.live.send_realtime_input(audio_stream_end=True)
                room.grant_next()
                await room.broadcast(room.public_state())
            elif t == "done" and room.release_floor(mid):
                room.talking.discard(mid)
                if room.live:
                    await room.live.send_realtime_input(audio_stream_end=True)  # lets the teacher answer without waiting for silence
                log.info("floor-done", room=code, member=mid, audio_seconds=round(audio_s, 1))
                audio_s = 0.0
                await room.broadcast(room.public_state())
            elif t == "text" and room.live and room.may_speak(mid):
                room.talking.discard(mid)
                room.heard += " " + str(ev.get("text", ""))[:400]
                room.last_child_audio = time.time()
                await room.live.send_realtime_input(text=str(ev.get("text", ""))[:400])
                await room.broadcast({"type": "heard", "name": m.name, "delta": str(ev.get("text", ""))[:400] + " "})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.error("ws-error", room=code, member=mid, error=repr(e)[:300])
    finally:
        room.remove(mid)
        log.info("leave", room=code, member=mid, name=m.name, members=len(room.members), audio_seconds=round(audio_s, 1))
        if not room.members:  # nobody left: close after a grace period (a dropped connection or a reload can come back)
            room.closer = asyncio.create_task(_close_later(room))
        else:
            await room.broadcast(room.public_state())


async def _close_later(room: Room) -> None:
    await asyncio.sleep(GRACE_SECONDS)
    if room.members:
        return
    if room.task:
        room.task.cancel()
    ROOMS.pop(room.code, None)
    log.info("room-closed", room=room.code, minutes=round((time.time() - room.created) / 60, 1))
