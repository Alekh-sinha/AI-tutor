"""Tools of the live teacher (called by the Gemini Live model, gemini-3.8-live). The board is ONE SCREEN AT A TIME: `show_screen` replaces everything on it (a heading, one picture or figure from the catalog, a few notes), so old and new never mix.
`ask_question` tells the system that a question is open and the class must wait for a child; `check_answer` judges the answer. They act on the room's `Turn` (a ContextVar set by session.py) and push events that session.py forwards to every child.
Calling convention (session.py): `prepare_class`, `plan` and `check_answer` are BLOCKING (the model waits for the result); all the others are NON_BLOCKING and answered with scheduling SILENT, so the teacher keeps talking while the screen changes.
Pictures and figures are made in the planning stage (live/prepare.py); `draw_picture` and `draw_html` make a NEW picture or figure when the prepared catalog does not show what a child's question or the idea needs: they add to the catalog (she is told when it is ready) and she then shows it with show_screen."""

import asyncio
import time

from ai_teacher_api.common import logsetup, picturegen
from ai_teacher_api.common.settings import WEB_PUBLIC
from ai_teacher_api.live import figures, judge, prepare
from ai_teacher_api.tutor import agent as tutor

log = logsetup.get("live")

MAX_DRAWN_IN_CLASS = 3
MAX_NOTES = 4
MAX_NOTES_WITH_FIGURE = 2


def _room():
    turn = tutor.CURRENT.get()
    return turn, turn.extra.get("room")


async def show_screen(heading: str = "", picture: str = "", figure: str = "", notes: list[str] | None = None) -> dict:
    """Put a NEW screen on the board: it REPLACES everything that was there. Call it at the moment you start talking about what it shows (a teacher writes or shows first, then explains), never after you have finished explaining it.
    Put together in ONE call whatever belongs on this screen (any mix of a heading, a picture, a figure and key words that suits the idea); anything you leave out disappears.

    Args:
        heading: optional title of the screen, at most 6 Hindi words.
        picture: optional name of ONE picture from the catalog.
        figure: optional name of ONE figure from the catalog (an HTML board: labelled parts, steps, a comparison or table, a scale, cause and effect). A picture and a figure together are allowed when the idea needs both, but they share a small screen.
        notes: optional key words or short lines to write (at most 4, each at most 6 words, Hindi); the concepts you want the children to remember.
    """
    turn, room = _room()
    figs = room.figures if room else {}
    if picture and picture not in turn.lesson_pictures:
        return {"status": "error", "error": f"no such picture; choose from {sorted(turn.lesson_pictures)}"}
    if figure and figure not in figs:
        return {"status": "error", "error": f"no such figure; choose from {sorted(figs)}"}
    if not (heading.strip() or picture or figure or [n for n in (notes or []) if n.strip()]):
        return {"status": "error", "error": "an empty screen: say what to show"}
    els: list[dict] = []
    if heading.strip():
        els.append({"type": "note", "id": tutor._new_id("n"), "text": heading.strip()[:80], "style": "heading"})
    if picture:
        caption = (room.catalog.get(picture, {}) if room else {}).get("caption", "")
        els.append({"type": "image", "id": tutor._new_id("i"), "src": turn.lesson_pictures[picture], "name": picture, "caption": caption})
    if figure:
        els.append({"type": "figure", "id": tutor._new_id("f"), "name": figure, "html": figs[figure]["html"], "caption": figs[figure].get("caption", "")})
    shown_text = {e.get("caption", "") for e in els} | {e.get("text", "") for e in els}
    limit = MAX_NOTES_WITH_FIGURE if figure else MAX_NOTES  # a figure shrinks to the room left: with it on screen only the most important words
    for n in [n.strip()[:80] for n in (notes or []) if n.strip() and n.strip()[:80] not in shown_text][:limit]:  # a note that repeats the heading or a caption is dropped
        els.append({"type": "note", "id": tutor._new_id("n"), "text": n, "style": "body"})
    turn.board[:] = els
    tutor._push({"type": "board", "op": "set", "els": els})
    if room:
        room.used.update(x for x in (picture, figure) if x)
    return {"status": "ok"}


async def ask_question(question: str, expected_answer: str) -> dict:
    """Call this when you ask the children a QUESTION that they should answer, right after you have said it. The system then waits for a child; you must stay silent until a child answers (or you are told nobody did).
    Do not call it for a rhetorical question that you answer yourself.

    Args:
        question: the question you asked, in Hindi.
        expected_answer: the correct answer you have in mind, in one short sentence.
    """
    turn, room = _room()
    if room:
        room.open_question = {"q": question.strip()[:300], "expected": expected_answer.strip()[:300], "hinted": False}
        await room.broadcast({"type": "question", "text": question.strip()[:300]})
    log.info("question-open", room=room.code if room else "", question=question[:200], expected=expected_answer[:200])
    return {"status": "ok", "now": "A child will answer. Say nothing more until you hear them."}


async def check_answer(question: str = "", expected_answer: str = "") -> dict:
    """Call this AFTER a child has answered your question and BEFORE you say anything about the answer. It checks the child's real words against the facts and returns the verdict
    (correct / partly / wrong / unclear) and what to say next. Follow it: never call an answer right unless the verdict is "correct", and never praise speech you could not understand.

    Args:
        question: the question you asked (leave empty to use the one opened with ask_question).
        expected_answer: the correct answer (leave empty to use the one from ask_question).
    """
    _, room = _room()
    oq = (room.open_question or room.last_question if room else None) or {}
    question, expected_answer = question or oq.get("q", ""), expected_answer or oq.get("expected", "")
    heard = room.heard if room else ""
    v = await judge.judge(question, expected_answer, heard, room.notes if room else "")
    if room:
        room.open_question = None
        await room.broadcast({"type": "question", "text": ""})
    return {"status": "ok", "verdict": v["verdict"], "why": v["reason"], "say_next": v["teacher_should_say"], "rule": "follow the verdict; do not call it right unless verdict is correct"}


async def _announce(room, text: str) -> None:
    """Tell the teacher (without starting a turn) that something she asked for is ready."""
    if room and room.live:
        from google.genai import types
        try:
            await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=False)
        except Exception as e:  # noqa: BLE001
            log.warn("announce-failed", room=room.code, error=repr(e)[:200])


async def draw_picture(description: str, caption: str = "") -> dict:
    """Draw a NEW illustration when no catalog picture shows what you need (typically a child's doubt about something the prepared material does not cover) and seeing it would help more than words. It takes up to a minute to be drawn,
    so say aloud that you are drawing it and keep explaining in words; you are told when it is ready, then show it with show_screen. A class has room for 3 of these. Describe ONE frozen moment in which the idea is visible (who or what is doing what, with its visible effect), never text or arrows.

    Args:
        description: concrete English description of the scene, at most 40 words.
        caption: at most 4 Hindi words naming what it shows.
    """
    turn, room = _room()
    if room and room.drawn >= MAX_DRAWN_IN_CLASS:
        return {"status": "error", "error": "you already drew the most pictures allowed in this class: explain in words or use the catalog"}
    if room:
        room.drawn += 1
    code = room.code if room else turn.session_id
    name = tutor._new_id("pd").replace("-", "_")
    tutor._push({"type": "thinking", "text": "🎨 चित्र बन रहा है…"})

    async def work() -> None:
        res = await picturegen.draw(description[:300], WEB_PUBLIC / "chat" / f"class-{code}" / f"{name}.webp", prepare.LIVE_STYLE)
        tutor._push({"type": "thinking", "text": ""})
        log.info("draw-picture-done", room=code, name=name, status=res.get("status"), error=res.get("error", ""), seconds=res.get("seconds", ""))
        if res.get("status") == "ok":
            turn.lesson_pictures[name] = f"/chat/class-{code}/{name}.webp"
            if room:
                room.catalog[name] = {"caption": caption.strip()[:40]}
            await _announce(room, f"(The picture you asked for is ready: {name} — {description[:200]}. Show it with show_screen when it fits.)")

    asyncio.create_task(work())  # keeps the ContextVar (the Turn) of this call
    return {"status": "started", "note": "you will be told when it is ready; keep teaching"}


async def draw_html(description: str, caption: str = "") -> dict:
    """Write a NEW figure (a labelled diagram, table, scale, cause -> effect boxes, steps in order, small animation) when no catalog figure shows what you need and a figure would make it clearer than a picture or words. It takes 15-30 seconds,
    so say aloud that you are drawing it and keep explaining in words; you are told when it is ready, then show it with show_screen. A class has room for 3 of these.

    Args:
        description: English instruction to the figure writer: which Hindi labels to show and how they are arranged (3-6 elements), at most 70 words. No drawings of objects or people, no diagonal lines.
        caption: at most 4 Hindi words.
    """
    turn, room = _room()
    if room and room.figs_drawn >= MAX_DRAWN_IN_CLASS:
        return {"status": "error", "error": "you already wrote the most figures allowed in this class: explain in words or use the catalog"}
    if room:
        room.figs_drawn += 1
    name = tutor._new_id("fd").replace("-", "_")
    tutor._push({"type": "thinking", "text": "✏️ आकृति बन रही है…"})

    async def work() -> None:
        from google import genai

        from ai_teacher_api.common.settings import PROJECT, TEXT_LOCATION
        t0 = time.time()
        try:
            html, problems = await figures.write_figure(genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION), description[:500])
        except Exception as e:  # noqa: BLE001
            html, problems = "", [repr(e)[:200]]
        tutor._push({"type": "thinking", "text": ""})
        log.info("draw-html-done", room=room.code if room else "", name=name, ok=not problems, problems=problems, seconds=round(time.time() - t0, 1))
        if not problems and room:
            room.figures[name] = {"html": html, "caption": caption.strip()[:40], "step": "asked by a child", "intent": "", "description": description[:200]}
            await _announce(room, f"(The figure you asked for is ready: {name} — {description[:200]}. Show it with show_screen when it fits.)")

    asyncio.create_task(work())
    return {"status": "started", "note": "you will be told when it is ready; keep teaching"}


async def prepare_class(topic: str) -> dict:
    """Prepare a class on a topic the children asked for. Call this ONCE, right after telling the children in one sentence that you are preparing. It takes a few minutes: it writes class notes, makes the pictures and figures of the class
    (the children see the progress). You get back the class notes and the catalog of pictures and figures you may show with show_screen.

    Args:
        topic: what the children want to learn, as they said it.
    """
    turn, room = _room()

    async def progress(text: str) -> None:
        tutor._push({"type": "thinking", "text": text})

    r = await prepare.prepare_topic(room.code if room else turn.session_id, topic, progress)
    if r.get("refused"):
        return {"status": "refused", "tell_the_children": r["refused"]}
    turn.lesson_pictures.update({k: v["src"] for k, v in r["pictures"].items()})
    if room:
        room.notes += "\n\nCLASS NOTES:\n" + r["notes"]
        room.figures = r["figures"]
        room.catalog.update({k: {"caption": v["caption"]} for k, v in r["pictures"].items()})
    return {"status": "ok", "class_notes": r["notes"], "suggested_steps": r["steps"], "catalog": r["catalog"]}


async def finish_class() -> dict:
    """Call this once, after the recap and the home activity have been spoken: the class is over and the children may now talk freely with you."""
    _, room = _room()
    if room:
        room.finished = True
        await room.broadcast(room.public_state())
    log.info("class-finished", room=room.code if room else "")
    return {"status": "ok", "now": "Invite the children to ask anything about today's lesson. From now on answer their questions one at a time, simply and briefly, with a screen if it helps. No new steps."}


TOOLS = [tutor.plan, show_screen, ask_question, check_answer, draw_picture, draw_html, prepare_class, finish_class]
BLOCKING = {"prepare_class", "plan", "check_answer"}  # the model waits for these (and then goes on speaking by itself); everything else runs while she keeps talking, answered SILENT
