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


def test_a_failed_picture_or_figure_is_reported_to_the_teacher_and_not_counted(monkeypatch):
    from ai_teacher_api.common import picturegen
    from ai_teacher_api.live import figures
    told = []

    async def announce(room, text):
        told.append(text)

    async def bad_draw(*a, **k):
        return {"status": "error", "error": "429 quota"}

    async def bad_figure(client, description):
        return "", ["labels overlap"]
    monkeypatch.setattr(tools, "_announce", announce)
    monkeypatch.setattr(picturegen, "draw", bad_draw)
    monkeypatch.setattr(figures, "write_figure", bad_figure)

    async def go():
        room, _ = _setup()
        await tools.draw_picture("a brake pad on a wheel rim", "ब्रेक")
        await tools.draw_html("pad, rim, friction", "ब्रेक")
        await asyncio.sleep(0.3)
        return room

    room = asyncio.run(go())
    assert any("could NOT be drawn" in t and "draw_html" in t for t in told)
    assert any("could NOT be made" in t for t in told)
    assert room.drawn == 0 and room.figs_drawn == 0


def test_show_screen_reply_says_what_the_item_really_shows():
    room, turn = _setup()
    room.catalog["p1"] = {"caption": "गेंद", "shows": "a ball stopping on mud"}
    room.figures["f1"]["shows"] = "tyre grooves with water flowing out"
    r = asyncio.run(tools.show_screen(heading="ब्रेक", picture="p1", figure="f1"))
    assert any("a ball stopping on mud" in x for x in r["this_screen_shows"]) and any("tyre grooves" in x for x in r["this_screen_shows"])
    assert r["your_heading"] == "ब्रेक" and "draw_html" in r["check"]
    assert "check" not in asyncio.run(tools.show_screen(heading="सिर्फ़ शीर्षक"))  # a screen of words only has nothing to compare
