import asyncio

import pytest

from ai_teacher_api.tutor import agent as tutor


def make_turn():
    return tutor.Turn(queue=asyncio.Queue(), session_id="test-session", lesson_pictures={"p": "/img/p.webp"})


@pytest.fixture
def no_tts(monkeypatch):
    import ai_teacher_api.common.tts as tts

    async def fake(*a, **k):
        return b"\x00\x00" * 100

    monkeypatch.setattr(tts, "synth_retry", fake)
    monkeypatch.setattr(tutor, "_tts_client", lambda: None)


async def test_board_keeps_five_notes_and_hides_the_oldest():
    t = make_turn()
    tutor.CURRENT.set(t)
    for i in range(7):
        await tutor.write_on_board(f"note {i}")
    notes = [e for e in t.board if e["type"] == "note"]
    assert len(notes) == 5 and notes[0]["text"] == "note 2"
    hides = [q for q in list(t.queue._queue) if q.get("op") == "hide"]
    assert len(hides) == 2


async def test_lesson_picture_must_exist():
    tutor.CURRENT.set(make_turn())
    assert (await tutor.show_lesson_picture("nope"))["status"] == "error"
    assert (await tutor.show_lesson_picture("p", "कुल्हड़"))["status"] == "ok"


async def test_nothing_more_is_said_after_a_question(no_tts):
    t = make_turn()
    tutor.CURRENT.set(t)
    assert (await tutor.say("क्या आप जानते हैं?"))["status"] == "ok"
    assert t.waiting
    assert (await tutor.say("लेकिन मैं जवाब भी देता हूँ"))["status"] == "error"
    assert t.said == 1


async def test_say_survives_tts_failure(monkeypatch):
    import ai_teacher_api.common.tts as tts

    async def boom(*a, **k):
        raise RuntimeError("tts down")

    monkeypatch.setattr(tts, "synth_retry", boom)
    monkeypatch.setattr(tutor, "_tts_client", lambda: None)
    t = make_turn()
    tutor.CURRENT.set(t)
    assert (await tutor.say("नमस्ते"))["status"] == "ok"
    ev = t.queue.get_nowait()
    assert ev["type"] == "say" and ev["audio"] is None  # the caption still shows


def test_lesson_context_live_vs_ask():
    lesson = {"title": "T", "narration": [{"start": 0, "end": 5, "text": "पहला"}, {"start": 5, "end": 9, "text": "दूसरा"}], "events": [{"type": "clear", "t": 0}, {"type": "image", "id": "p", "src": "/s", "caption": "c"}, {"type": "image", "id": "p~q", "src": "/s", "caption": "c"}, {"type": "anim", "target": "p", "effect": "pulse"}]}
    ask, pics = tutor.lesson_context(lesson, 6, "points", [], live=False)
    live, _ = tutor.lesson_context(lesson, 6, "points", [], live=True)
    assert "HAS TAUGHT" in ask and "RECORDED LESSON" in live and pics == {"p": "/s"}


async def test_draw_picture_goes_without_when_the_image_quota_is_full(monkeypatch):
    from ai_teacher_api.common import picturegen

    called = []

    async def draw(*a, **k):
        called.append(1)
        return {"status": "ok"}

    monkeypatch.setattr(picturegen, "wait_seconds", lambda: 90.0)
    monkeypatch.setattr(picturegen, "draw", draw)
    t = make_turn()
    tutor.CURRENT.set(t)
    r = await tutor.draw_picture("a kulhad")
    assert r["status"] == "error" and "not available at this moment" in r["error"] and not called and not t.board


async def test_draw_picture_gives_up_after_the_time_limit(monkeypatch):
    from ai_teacher_api.common import picturegen

    async def slow(*a, **k):
        await asyncio.sleep(10)

    monkeypatch.setattr(picturegen, "wait_seconds", lambda: 0.0)
    monkeypatch.setattr(picturegen, "draw", slow)
    monkeypatch.setattr(tutor, "IMAGE_TOTAL_S", 0.05)
    tutor.CURRENT.set(make_turn())
    r = await tutor.draw_picture("a kulhad")
    assert r["status"] == "error" and "not available at this moment" in r["error"]


async def test_draw_picture_success_shows_the_picture_and_returns_it(monkeypatch, tmp_path):
    from PIL import Image

    from ai_teacher_api.common import picturegen

    async def draw(description, path, *a, **k):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 30), "red").save(path, "WEBP")
        return {"status": "ok", "seconds": 1.0}

    monkeypatch.setattr(picturegen, "wait_seconds", lambda: 0.0)
    monkeypatch.setattr(picturegen, "draw", draw)
    monkeypatch.setattr(tutor, "WEB_PUBLIC", tmp_path)
    t = make_turn()
    tutor.CURRENT.set(t)
    r = await tutor.draw_picture("a kulhad", "कुल्हड़")
    assert r["status"] == "ok" and r["photo"] is not None
    assert [e for e in t.board if e["type"] == "image"][0]["caption"] == "कुल्हड़"
