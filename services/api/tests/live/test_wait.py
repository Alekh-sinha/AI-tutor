"""wait_for_answer: the interrupt tool. A child's typed or spoken answer is collected by the server and returned to the teacher with a verdict."""
import asyncio

from ai_teacher_api.live import hear, judge, tools
from ai_teacher_api.live.room import Member, Room
from ai_teacher_api.tutor import agent as tutor


def _setup():
    async def noop(_): ...
    room = Room(code="9", host_key="k")
    room.add(Member(id="a", name="a", send=noop, send_bytes=noop, is_host=True))
    room.floor = "a"
    turn = tutor.Turn(queue=asyncio.Queue(), session_id="t", lesson_pictures={})
    turn.extra["room"] = room
    tutor.CURRENT.set(turn)
    return room


def _judge(monkeypatch, verdict="correct"):
    async def fake(q, e, heard, notes):
        return {"verdict": verdict, "reason": "r", "teacher_should_say": "ठीक"}
    monkeypatch.setattr(judge, "judge", fake)


def test_typed_answer_is_returned_with_the_verdict_and_the_wait_is_closed(monkeypatch):
    _judge(monkeypatch)

    async def go():
        room = _setup()
        t = asyncio.create_task(tools.wait_for_answer("कौन सा बल?", "घर्षण"))
        await asyncio.sleep(0.3)
        assert room.waiting and room.open_question["q"] == "कौन सा बल?"
        room.waiting["text"] += " घर्षण"
        room.waiting["event"].set()
        return room, await t

    room, r = asyncio.run(go())
    assert r["status"] == "answered" and r["child_said"] == "घर्षण" and r["verdict"] == "correct"
    assert room.waiting is None and room.open_question is None and room.last_question["q"] == "कौन सा बल?"


def test_spoken_answer_is_transcribed_on_the_server(monkeypatch):
    _judge(monkeypatch, "wrong")

    async def fake_transcribe(pcm):
        assert pcm == b"\x01\x00" * 10
        return "बिजली"
    monkeypatch.setattr(hear, "transcribe", fake_transcribe)

    async def go():
        room = _setup()
        t = asyncio.create_task(tools.wait_for_answer("q", "e"))
        await asyncio.sleep(0.3)
        room.waiting["audio"] += b"\x01\x00" * 10
        room.waiting["event"].set()
        return await t

    r = asyncio.run(go())
    assert r["child_said"] == "बिजली" and r["verdict"] == "wrong"


def test_nobody_answers_and_host_skip(monkeypatch):
    _judge(monkeypatch)
    monkeypatch.setattr(tools, "ANSWER_QUIET", 0.3)

    async def go():
        room = _setup()
        r1 = await tools.wait_for_answer("q", "e")
        t = asyncio.create_task(tools.wait_for_answer("q2", "e"))
        await asyncio.sleep(0.3)
        room.waiting["skip"] = True
        room.waiting["event"].set()
        return r1, await t

    r1, r2 = asyncio.run(go())
    assert r1["status"] == "no_answer" and r2["status"] == "skipped"


def test_unclear_speech_is_never_judged(monkeypatch):
    _judge(monkeypatch)

    async def fake_transcribe(pcm):
        return "[unclear]"
    monkeypatch.setattr(hear, "transcribe", fake_transcribe)

    async def go():
        room = _setup()
        t = asyncio.create_task(tools.wait_for_answer("q", "e"))
        await asyncio.sleep(0.3)
        room.waiting["audio"] += b"\x01\x00" * 10
        room.waiting["event"].set()
        return await t

    assert asyncio.run(go())["verdict"] == "unclear"


def test_state_log_reports_only_changes(monkeypatch):
    room = _setup()
    room.log_state("first")
    seen = []
    monkeypatch.setattr("ai_teacher_api.live.room.log", type("L", (), {"info": staticmethod(lambda *a, **k: seen.append(k))})())
    room.log_state("nothing changed")
    room.teacher_busy = True
    room.log_state("busy now")
    assert len(seen) == 1 and seen[0]["changed"] == {"busy": [False, True]} and seen[0]["why"] == "busy now"


def test_without_an_expected_answer_the_reply_is_returned_unjudged(monkeypatch):
    async def boom(*a):
        raise AssertionError("must not be judged")
    monkeypatch.setattr(judge, "judge", boom)

    async def go():
        room = _setup()
        t = asyncio.create_task(tools.wait_for_answer("समझ आया?"))
        await asyncio.sleep(0.3)
        room.waiting["text"] += " हाँ"
        room.waiting["event"].set()
        return await t

    r = asyncio.run(go())
    assert r["child_said"] == "हाँ" and r["verdict"] == "not_judged"


def test_a_child_question_answered_only_by_tools_is_nudged_up_to_three_times():
    from ai_teacher_api.live import session
    assert session.MAX_ANSWER_NUDGES == 3
    room = _setup()
    room.owes_answer = 1.0
    nudge = lambda said: bool(room.owes_answer) and not (len(said.split()) >= 6) and not room.waiting and room.answer_nudges < session.MAX_ANSWER_NUDGES
    assert nudge("")
    room.answer_nudges = 3
    assert not nudge("")
