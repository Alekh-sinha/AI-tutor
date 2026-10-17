"""A child's utterance (already transcribed) -> the teacher. If a question is open the answer is checked by judge.py first; the teacher then receives the words AND the verdict as text, so she cannot
praise a wrong or unintelligible answer on her own."""

from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.live import judge
from ai_teacher_api.live.room import Room

log = logsetup.get("live")


def message(name: str, heard: str, question: str, verdict: dict | None) -> str:
    unclear = not heard.strip() or not heard.replace("[unclear]", "").strip()
    if unclear:
        return f"(Child {name} spoke but could not be understood. Kindly ask them to say it once more, slowly. Do not praise or judge anything.)"
    if question and verdict:
        return (f"(Child {name} answered your question «{question}». Their words: «{heard}». The answer checker says: {verdict['verdict'].upper()} — {verdict['reason']} "
                f"Suggested next words: {verdict['teacher_should_say']} Follow the verdict: do not call it right unless it is CORRECT; if partly or wrong, give a hint and ask again.)")
    return f"(Child {name} says: «{heard}»)"


async def deliver(room: Room, name: str, heard: str) -> None:
    heard = heard.strip()
    if not room.live:
        return
    question, verdict = room.last_question, None
    clear = heard.replace("[unclear]", "").strip()
    if question and clear:
        try:
            verdict = await judge.judge(question, "(work it out from the class notes)", heard, room.notes)
        except Exception as e:  # noqa: BLE001 - without a verdict she is told to be careful, never to praise
            log.error("judge-failed", room=room.code, error=repr(e)[:300])
            verdict = {"verdict": "unclear", "reason": "the answer could not be checked", "teacher_should_say": "Ask the child to say it once more."}
    await room.broadcast({"type": "heard", "name": name, "delta": heard or "…"})
    log.info("child-said", room=room.code, name=name, heard=heard[:200], question=question[:160], verdict=(verdict or {}).get("verdict", ""))
    room.last_question = ""
    if room.teacher_busy:
        room.discard = True  # the child spoke over her: the rest of what she was saying is dropped
    room.teacher_busy = True
    await room.broadcast(room.public_state())
    await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=message(name, heard, question, verdict))]), turn_complete=True)
