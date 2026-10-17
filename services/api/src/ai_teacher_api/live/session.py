"""The live teacher of one room: ONE Gemini Live session (gemini-3.8-live, native audio) that streams the teacher's voice to every child, runs the board tools while she talks, and hears the child who holds the floor.

Data flow: children's microphones (16 kHz PCM, only the floor holder's, gated in room.py) -> `room.live.send_realtime_input` ; Live API -> audio chunks (24 kHz PCM, paced about in real time) broadcast to everyone, spoken-text
transcripts (captions), tool calls (board/plan/pictures), `interrupted` (a child spoke over the teacher), `turn_complete` (floor handover). Tool calls run as background tasks so the receive loop never stalls; blocking
tools (prepare_class, check_answer) make the model wait, the others are answered SILENT and she keeps talking. Logs: logs/live.jsonl."""

import asyncio
import re
import time

from google import genai
from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import LIVE_LOCATION, LIVE_MODEL, PROJECT
from ai_teacher_api.live import judge, prompt, tools
from ai_teacher_api.live.room import Room
from ai_teacher_api.tutor import agent as tutor

log = logsetup.get("live")
PRAISE = re.compile(r"(बिल्कुल|सही|शाबाश|वाह|बहुत अच्छे|अच्छा जवाब|ठीक कहा|तुमने ठीक)")
SELF_ANSWER = re.compile(r"\?\s*(बिल्कुल|सही|शाबाश|वाह|ठीक कहा|तुमने)")
CONTINUE_GAP = 0.8  # seconds of quiet after her speech has been played, before she is told to go on (no question was open)
QUESTION_WAIT = 15.0  # seconds a question stays open for a child (push-to-talk or typing) before she hints or answers
MAX_RECONNECTS = 3
MAX_SESSION_SECONDS = 25 * 60


def _declarations(client) -> list[types.FunctionDeclaration]:
    out = []
    for fn in tools.TOOLS:
        d = types.FunctionDeclaration.from_callable(client=client, callable=fn)
        d.response = None
        d.behavior = types.Behavior.BLOCKING if fn.__name__ in tools.BLOCKING else types.Behavior.NON_BLOCKING
        out.append(d)
    return out


def build_config(client, instruction: str, voice: str, handle: str | None) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=instruction,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        realtime_input_config=types.RealtimeInputConfig(automatic_activity_detection=types.AutomaticActivityDetection(
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW, end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            prefix_padding_ms=200, silence_duration_ms=700)),  # less trigger-happy: a cough or a speaker's echo should not cut the teacher off
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        tools=[types.Tool(function_declarations=_declarations(client))],
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        session_resumption=types.SessionResumptionConfig(handle=handle),
    )


async def _forward(room: Room, turn: tutor.Turn) -> None:
    """Board/plan/status events produced by tools -> every child."""
    while True:
        ev = await turn.queue.get()
        if ev["type"] == "plan":
            room.plan = ev["steps"]
            await room.broadcast({"type": "plan", "steps": ev["steps"]})
        elif ev["type"] in ("board", "thinking"):
            await room.broadcast(ev)


async def _hand_over(room: Room) -> None:
    """The teacher finished a turn: the floor goes to the next child (or stays open in a solo room)."""
    room.teacher_busy = False
    before = room.floor
    room.floor = None
    room.grant_next()
    log.info("floor", room=room.code, was=before, now=room.floor, queue=len(room.queue))
    await room.broadcast(room.public_state())


async def _watch_floor(room: Room) -> None:
    while True:
        await asyncio.sleep(2)
        if not room.teacher_busy and (room.floor_expired() or (room.floor is None and room.queue)):
            log.info("floor-timeout" if room.floor else "floor-grant", room=room.code, holder=room.floor)
            await _hand_over(room)


async def _run_tool(room: Room, turn: tutor.Turn, s, fc: types.FunctionCall, state: dict) -> None:
    """Run one tool call in the background and answer it. Blocking tools: a plain answer (the model was waiting). The others: scheduling SILENT (she carries on talking and does not comment)."""
    fn = next((f for f in tools.TOOLS if f.__name__ == fc.name), None)
    t0 = time.time()
    if fc.name == "check_answer":
        state["checked"] = True
    try:
        result = await fn(**(fc.args or {})) if fn else {"status": "error", "error": "unknown tool"}
    except Exception as e:  # noqa: BLE001 - tell the model, keep the class going
        result = {"status": "error", "error": repr(e)[:200]}
        log.error("tool-failed", room=room.code, tool=fc.name, error=repr(e)[:300])
    result = {**result, "board_now": room.board_status(turn.lesson_pictures)}  # she cannot see the children's screen: every answer tells her what is on it
    log.info("tool", room=room.code, tool=fc.name, args=fc.args, status=result.get("status"), seconds=round(time.time() - t0, 1), board_now=result["board_now"])
    extra = {} if fc.name in tools.BLOCKING else {"scheduling": types.FunctionResponseScheduling.SILENT}
    try:
        await s.send_tool_response(function_responses=[types.FunctionResponse(id=fc.id, name=fc.name, response=result, **extra)])
    except Exception as e:  # noqa: BLE001 - the session may have ended meanwhile
        log.warn("tool-response-failed", room=room.code, tool=fc.name, error=repr(e)[:200])


def idle_action(room: Room, state: dict, now: float) -> str | None:
    """What the idle watcher should do now: "continue" (no question is open, she is quiet), "hint" (a question has been open QUESTION_WAIT with no answer: she is told once to hint or answer and go on), or None.
    Pure function of the room and the state (unit-tested: a question that stayed open after the hint once stalled the whole class)."""
    if not (room.live and room.started and not room.finished and room.members and not room.teacher_busy and not room.talking and state["pending_tools"] == 0):
        return None
    quiet = now - max(state["last_msg"], state["play_end"])
    child_quiet = now - room.last_child_audio
    if room.open_question:
        return "hint" if quiet >= QUESTION_WAIT and child_quiet >= QUESTION_WAIT else None
    return "continue" if quiet >= CONTINUE_GAP and child_quiet >= CONTINUE_GAP else None


async def _watch_idle(room: Room, state: dict) -> None:
    """She must never stall while nobody holds the microphone (see idle_action). After the hint the question is CLOSED (kept as room.last_question for a late answer): she hints, answers or re-asks with ask_question.
    Every nudge starts with the board status. No limit on the number of continues: a class ends with finish_class, the host leaving or the time cap."""
    while True:
        await asyncio.sleep(0.25)
        now = time.time()
        action = idle_action(room, state, now)
        if not action:
            continue
        if action == "hint":
            text, kind = prompt.NO_ANSWER, "no-answer-hint"
            room.last_question, room.open_question = room.open_question, None
        else:
            text, kind = prompt.AUTO_CONTINUE, "auto-continue"
        state["auto"] += 1
        state["last_msg"] = now
        state["last_nudge"] = now
        board = room.board_status(state["pictures"])
        log.info(kind, room=room.code, n=state["auto"], quiet=round(now - state["play_end"], 1), board=board)
        room.teacher_busy = True
        try:
            await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=f"{board}\n{text}")]), turn_complete=True)
        except Exception as e:  # noqa: BLE001
            log.warn(f"{kind}-failed", room=room.code, error=repr(e)[:200])


async def _tell_board(room: Room, turn: tutor.Turn) -> None:
    """After each of her turns: the board as the children see it now, added to her context WITHOUT starting a new turn (whatever comes next, a child's answer or 'go on', she has read it)."""
    if not room.live:
        return
    status = room.board_status(turn.lesson_pictures)
    try:
        await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=f"(Status, not a request: {status})")]), turn_complete=False)
        log.info("board-status", room=room.code, status=status)
    except Exception as e:  # noqa: BLE001
        log.warn("board-status-failed", room=room.code, error=repr(e)[:200])


async def _verify_answer(room: Room, state: dict, s, question: str, expected: str = "") -> None:
    """Safety net for the speech model's habit of praising whatever a child says. When a child has answered and she starts replying WITHOUT having called check_answer, the answer is judged by a separate model
    in parallel; if it is not correct and she has already praised it, she is cut off and told to correct herself."""
    await asyncio.sleep(1.2)  # the transcript of the child's last words may still be arriving
    heard = room.heard.strip()
    if state["checked"] or not heard:
        return
    try:
        v = await judge.judge(question, expected or "(work it out from the class notes)", heard, room.notes)
    except Exception as e:  # noqa: BLE001
        log.error("verify-failed", room=room.code, error=repr(e)[:300])
        return
    praised = bool(PRAISE.search(state["said"]))
    log.info("answer-verified", room=room.code, heard=heard[:160], verdict=v["verdict"], praised=praised, said_so_far=state["said"][-160:])
    if v["verdict"] == "correct" or not praised:
        return
    log.warn("answer-praised-wrongly", room=room.code, heard=heard[:160], verdict=v["verdict"], reason=v["reason"][:200])
    room.discard = True
    await room.broadcast({"type": "interrupted"})
    if room.live:
        await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=(
            f"(STOP. The answer checker says the child's answer «{heard}» is {v['verdict'].upper()}: {v['reason']} You just praised it by mistake. Say kindly that it is not quite right, "
            f"give a hint or a simpler question and ask again. Suggested words: {v['teacher_should_say']} Do not repeat what you said before.)"))]), turn_complete=True)


async def _handle(room: Room, turn: tutor.Turn, s, m: types.LiveServerMessage, state: dict) -> str | None:
    """One message from the Live API. Returns "reconnect" when the server announces the end of this connection."""
    state["last_msg"] = time.time()
    if m.session_resumption_update and m.session_resumption_update.new_handle:
        state["handle"] = m.session_resumption_update.new_handle
    if m.go_away:
        log.warn("go-away", room=room.code, time_left=str(m.go_away.time_left))
        return "reconnect"
    if m.data and room.discard:
        return None  # the child barged in: the rest of that turn is not played
    if (m.data or (m.server_content and m.server_content.output_transcription)) and not state["verifying"] and room.open_question and time.time() - room.last_child_audio < 20:
        state["verifying"] = True  # a child answered the open question and she has started to reply
        asyncio.create_task(_verify_answer(room, state, s, room.open_question["q"], room.open_question["expected"]))
    if m.data:
        if not room.teacher_busy:
            room.teacher_busy = True
            await room.broadcast(room.public_state())
        state["audio_bytes"] += len(m.data)
        state["play_end"] = max(state["play_end"], time.time()) + len(m.data) / 48000  # 24 kHz 16-bit mono: when the children have heard everything sent so far
        await room.broadcast_bytes(m.data)
    sc = m.server_content
    if sc:
        if sc.output_transcription and sc.output_transcription.text and not room.discard:
            state["said"] += sc.output_transcription.text
            await room.broadcast({"type": "caption", "delta": sc.output_transcription.text})
        if sc.input_transcription and sc.input_transcription.text:
            room.last_child_audio = time.time()  # a child is really speaking (not just an open microphone)
            state["heard"] += sc.input_transcription.text
            room.heard += sc.input_transcription.text
            await room.broadcast({"type": "heard", "name": room.public_state()["floor_name"], "delta": sc.input_transcription.text})
        if sc.interrupted:
            log.info("interrupted", room=room.code, said=state["said"][-120:], since_nudge=round(time.time() - state["last_nudge"], 1), talking=bool(room.talking), since_child_audio=round(time.time() - room.last_child_audio, 1))
            room.discard = False
            state["auto"] = 0
            await room.broadcast({"type": "interrupted"})
        if sc.turn_complete:
            said = state["said"]
            log.info("teacher-turn", room=room.code, said=said, heard=state["heard"], seconds=round(time.time() - state["turn_t0"], 1),
                     audio_seconds=round(state["audio_bytes"] / 48000, 1), words=len(said.split()))  # words per audio second ~2.5-3.7 for Hindi; far above = sentences shown but not spoken
            if SELF_ANSWER.search(said):
                log.warn("self-answer-suspect", room=room.code, said=said, heard=state["heard"])  # a question followed by "सही!" inside ONE turn: nobody answered
            state["verifying"], state["checked"] = False, False
            state["tool_calls"] = 0
            if state["heard"].strip() and room.open_question:  # a child answered and she has replied: the question is done
                room.last_question, room.open_question = room.open_question, None
                await room.broadcast({"type": "question", "text": ""})
            if said.strip():
                last_sentence = (re.findall(r"[^.?!।]+[.?!।]*", said.strip()) or [""])[-1].strip()
                if last_sentence.endswith("?") and not room.open_question:  # she asked but forgot ask_question: still wait for the answer
                    room.open_question = {"q": last_sentence[:300], "expected": "", "hinted": False}
                    log.warn("question-without-tool", room=room.code, question=last_sentence[:200])
                state["turns"] += 1
                if room.open_question:
                    state["auto"] = 0
            state["audio_bytes"] = 0
            room.heard = ""
            room.discard = False
            state["said"], state["heard"], state["turn_t0"] = "", "", time.time()
            turn.new_pictures = 0
            await room.broadcast({"type": "caption_end"})
            await _hand_over(room)
            await _tell_board(room, turn)
    if m.tool_call:
        for fc in m.tool_call.function_calls:
            state["pending_tools"] += 1
            state["tool_calls"] += 1
            task = asyncio.create_task(_run_tool(room, turn, s, fc, state))
            task.add_done_callback(lambda _t: state.__setitem__("pending_tools", state["pending_tools"] - 1))
    return None


async def run_room(room: Room, instruction: str, pictures: dict[str, str], voice: str, first_message: str) -> None:
    """Runs until the class ends (host leaves, time cap, or repeated failures)."""
    client = genai.Client(vertexai=True, project=PROJECT, location=LIVE_LOCATION)
    turn = tutor.Turn(queue=asyncio.Queue(), session_id=f"room-{room.code}", lesson_pictures=pictures, voice=voice)
    turn.max_notes, turn.max_visuals = 4, 2  # the screen holds at most 4 notes and 2 pictures/figures; the server board is exactly what the children see
    tutor.CURRENT.set(turn)
    room.board = turn.board
    room.notes = instruction
    turn.extra["room"] = room
    state = {"handle": None, "said": "", "heard": "", "audio_bytes": 0, "turns": 0, "pictures": pictures, "verifying": False, "checked": False, "tool_calls": 0, "pending_tools": 0, "auto": 0, "last_msg": time.time(), "turn_t0": time.time(), "play_end": 0.0, "hinted": False, "last_nudge": 0.0}
    helpers = [asyncio.create_task(_forward(room, turn)), asyncio.create_task(_watch_floor(room)), asyncio.create_task(_watch_idle(room, state))]
    t_start, attempt = time.time(), 0
    try:
        while attempt <= MAX_RECONNECTS and time.time() - t_start < MAX_SESSION_SECONDS:
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=build_config(client, instruction, voice, state["handle"])) as s:
                    room.live = s
                    log.info("connected", room=room.code, attempt=attempt, resumed=bool(state["handle"]))
                    if attempt == 0:
                        room.teacher_busy = True
                        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=first_message)]), turn_complete=True)
                    again = False
                    while not again:
                        async for m in s.receive():
                            if await _handle(room, turn, s, m, state) == "reconnect":
                                again = True
                                break
            except Exception as e:  # noqa: BLE001
                log.error("session-error", room=room.code, attempt=attempt, error=repr(e)[:400])
                if not room.members:
                    break
            finally:
                room.live = None
            attempt += 1
            if not room.members:
                break
        log.info("session-end", room=room.code, seconds=round(time.time() - t_start), attempts=attempt)
        await room.broadcast({"type": "ended", "reason": "कक्षा पूरी हुई।" if time.time() - t_start >= MAX_SESSION_SECONDS else "कक्षा से कनेक्शन टूट गया।"})
    finally:
        for h in helpers:
            h.cancel()
