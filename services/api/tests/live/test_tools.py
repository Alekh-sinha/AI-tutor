import asyncio

from ai_teacher_api.live import tools
from ai_teacher_api.live.room import Room
from ai_teacher_api.tutor import agent as tutor


def _setup():
    room = Room(code="9", host_key="k")
    room.figures = {"f1": {"html": '<div class="fig">घ</div>', "caption": "आकृति"}}
    room.catalog = {"p1": {"caption": "गेंद का रुकना"}}
    turn = tutor.Turn(queue=asyncio.Queue(), session_id="t", lesson_pictures={"p1": "/chat/x/p1.webp"})
    turn.extra["room"] = room
    turn.board = room.board
    tutor.CURRENT.set(turn)
    return room, turn


def test_show_screen_replaces_everything_and_marks_material_used():
    room, turn = _setup()
    asyncio.run(tools.show_screen(heading="शीर्षक", picture="p1", notes=["एक", "दो"]))
    assert [e["type"] for e in turn.board] == ["note", "image", "note", "note"]
    asyncio.run(tools.show_screen(heading="नया"))
    assert [e["text"] for e in turn.board] == ["नया"]  # nothing of the old screen stays
    assert "p1" in room.used
    ev = turn.queue.get_nowait()
    assert ev["op"] == "set"


def test_show_screen_drops_notes_that_repeat_the_caption_and_limits_notes_with_a_figure():
    room, turn = _setup()
    asyncio.run(tools.show_screen(heading="H", picture="p1", notes=["गेंद का रुकना", "H", "अलग बात"]))
    assert [e.get("text") for e in turn.board if e["type"] == "note"] == ["H", "अलग बात"]
    asyncio.run(tools.show_screen(figure="f1", notes=["a", "b", "c", "d"]))
    assert len([e for e in turn.board if e["type"] == "note"]) == tools.MAX_NOTES_WITH_FIGURE


def test_show_screen_rejects_unknown_names():
    _setup()
    assert asyncio.run(tools.show_screen(picture="nope"))["status"] == "error"
    assert asyncio.run(tools.show_screen(figure="f_nope"))["status"] == "error"
    assert asyncio.run(tools.show_screen())["status"] == "error"
