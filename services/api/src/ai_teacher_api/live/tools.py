"""Tools of the live teacher (called by the Gemini Live model, gemini-3.8-live). The board is ONE SCREEN AT A TIME: `show_screen` replaces everything on it (a heading, one picture or figure from the catalog, a few notes), so old and new never mix.
`wait_for_answer` is the interrupt tool: she asks a question aloud, naturally, then calls it; it collects the next child's answer (the microphone goes to the server, not to the speech model), transcribes and judges it and returns the words and the verdict. They act on the room's `Turn` (a ContextVar set by session.py) and push events that session.py forwards to every child.
Calling convention (session.py): `prepare_class`, `plan` and `wait_for_answer` are BLOCKING (the model waits for the result); all the others are NON_BLOCKING and answered with scheduling SILENT, so the teacher keeps talking while the screen changes.
Pictures and figures are made in the planning stage (live/prepare.py); `draw_picture` and `draw_html` make a NEW picture or figure when the prepared catalog does not show what a child's question or the idea needs: they add to the catalog (she is told when it is ready) and she then shows it with show_screen."""

import asyncio
import time

from ai_teacher_api.common import logsetup, picturegen
from ai_teacher_api.common.settings import WEB_PUBLIC
from ai_teacher_api.live import figures, judge, prepare
from ai_teacher_api.tutor import agent as tutor

log = logsetup.get("live")

MAX_DRAWN_IN_CLASS = 6  # pictures she may draw DURING the class (children's doubts); the pictures made before the class are separate
MAX_FIGS_IN_CLASS = 8
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
        for x in (picture, figure):
            room.ready_new.pop(x, None)
    result: dict = {"status": "ok"}
    shown = []  # what each catalog item on the screen really shows (its description, written when it was made): she must be able to compare it with what she is about to say
    if picture:
        shown.append(f"picture {picture}: {(room.catalog.get(picture, {}) if room else {}).get('shows') or (room.catalog.get(picture, {}) if room else {}).get('caption', '')}")
    if figure:
        f = figs.get(figure, {})
        shown.append(f"figure {figure}: {f.get('shows') or f.get('description') or f.get('caption', '')}")
    if shown:
        result["this_screen_shows"] = shown
        if heading.strip():
            result["your_heading"] = heading.strip()[:80]
        result["check"] = "Is this exactly what you are about to explain, and does your heading say what it shows? If not, make the right one with draw_html (or draw_picture) and keep explaining while it is made."
    return result


ANSWER_QUIET = 20.0  # seconds after her question was played, with nobody speaking or typing, before "nobody answered"
ANSWER_MAX = 150.0  # the longest a class waits for one answer
MAX_ANSWER_AUDIO = 25 * 32000  # bytes of a child's answer kept (25 s of 16 kHz 16-bit audio)


async def wait_for_answer(question: str, expected_answer: str = "") -> dict:
    """Call this RIGHT AFTER you have asked the children a question aloud and want them to answer. It is the only way an answer can reach you: until you call it the children's microphones are not listened to for an answer, so without the call you never hear them.
    The call waits for a child to answer (press-to-talk or typing) and returns what the child really said, a verdict (correct / partly / wrong / unclear) and what to say next. Say nothing between asking and calling.
    Do not call it for a rhetorical question that you answer yourself.

    Args:
        question: the question you just asked, in Hindi.
        expected_answer: the correct answer you have in mind, in one short sentence. Leave it empty if the question has no single right answer (then you only get the child's words, with no verdict).
    """
    from ai_teacher_api.live import hear

    _, room = _room()
    if not room:
        return {"status": "error", "error": "no class"}
    w = {"audio": bytearray(), "text": "", "event": asyncio.Event(), "skip": False}
    room.open_question = {"q": question.strip()[:300], "expected": expected_answer.strip()[:300], "hinted": False}
    room.waiting = w
    await room.broadcast({"type": "question", "text": "आपके जवाब की बारी है 🎤"})  # the question itself is spoken, never printed: what she says is what the children get
    room.log_state("wait-for-answer-start", question=question[:200], expected=expected_answer[:200])
    t0 = time.time()
    reason = "answered"
    while not w["event"].is_set():
        now = time.time()
        if now - t0 > ANSWER_MAX:
            reason = "too-long"
            break
        if not room.members:
            reason = "nobody-in-room"
            break
        if not room.talking and w["audio"] and now - room.last_child_audio > 3.0:
            break  # the child stopped speaking and the "done" message was lost
        if not room.talking and not w["audio"] and now - max(t0, room.play_end, room.last_child_audio) > ANSWER_QUIET:
            reason = "nobody-answered"
            break
        try:
            await asyncio.wait_for(w["event"].wait(), 0.25)
        except asyncio.TimeoutError:
            pass
    heard = w["text"].strip()
    if w["audio"] and not w["skip"]:
        try:
            heard = (heard + " " + await hear.transcribe(bytes(w["audio"]))).strip()
        except Exception as e:  # noqa: BLE001
            log.error("transcribe-failed", room=room.code, error=repr(e)[:300])
    room.waiting = None
    room.last_question, room.open_question = room.open_question, None
    room.heard = ""
    await room.broadcast({"type": "question", "text": ""})
    clear = heard.replace("[unclear]", "").strip()
    if w["skip"]:
        reason = "host-skipped"
        result = {"status": "skipped", "say_next": "The host pressed 'go on': do not wait any longer. Say the right answer with the reason behind it, and continue."}
    elif not heard:
        reason = reason if reason != "answered" else "empty"
        result = {"status": "no_answer", "waited_seconds": round(time.time() - t0), "say_next": "Nobody answered. Do not ask again: say the right answer kindly with the reason behind it, then go on."}
    elif not clear:
        result = {"status": "answered", "child_said": heard, "verdict": "unclear", "say_next": "A child spoke but could not be understood. Do not praise anything and do not ask again: kindly say the right answer with the reason behind it, then go on."}
    else:
        await room.broadcast({"type": "heard", "name": room.public_state()["floor_name"], "delta": heard})
        if not expected_answer.strip():
            room.log_state("wait-for-answer-end", reason=reason, heard=heard[:200], verdict="not_judged", waited=round(time.time() - t0, 1))
            return {"status": "answered", "child_said": heard, "verdict": "not_judged", "say_next": "No expected answer was given, so nothing was checked: respond to what the child said as a teacher would."}
        try:
            v = await judge.judge(question, expected_answer, heard, room.notes)
        except Exception as e:  # noqa: BLE001
            log.error("judge-failed", room=room.code, error=repr(e)[:300])
            v = {"verdict": "unclear", "reason": "the answer could not be checked", "teacher_should_say": "Ask the child to say it once more."}
        result = {"status": "answered", "child_said": heard, "verdict": v["verdict"], "why": v["reason"], "say_next": v["teacher_should_say"],
                  "rule": "never ask this question again. Praise only if the verdict is correct (say exactly what was right); otherwise say the right answer with the reason behind it. If the child asked a doubt of their own instead of answering, treat it as a doubt."}
    room.log_state("wait-for-answer-end", reason=reason, heard=heard[:200], verdict=result.get("verdict", result["status"]), waited=round(time.time() - t0, 1))
    return result


async def _announce(room, text: str) -> None:
    """Tell the teacher that something she asked for is ready (or failed). Without starting a turn, unless she is silent and a child's question is still waiting for her spoken answer: then this wakes her
    (seen 2026-10-17: a figure became ready after the class, the message did not start a turn, and she never answered)."""
    if room and room.live:
        from google.genai import types
        idle = not room.teacher_busy and not room.waiting
        wake = idle and (bool(room.owes_answer) or room.finished)  # in a running class the idle watcher goes on by itself; after the class nothing else would (seen 2026-10-17: two figures drawn for children's doubts were never shown)
        if wake:
            text += (" A child's question is still waiting for your spoken answer: explain it now, aloud, pointing into the screen." if room.owes_answer
                     else " This was for a child's doubt you answered: show it now with show_screen and walk the child through it in a few sentences.")
            room.teacher_busy = True
        try:
            await room.live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=wake)
        except Exception as e:  # noqa: BLE001
            log.warn("announce-failed", room=room.code, error=repr(e)[:200])


async def draw_picture(description: str, caption: str = "") -> dict:
    """Draw a NEW illustration when no catalog picture shows what you need (typically a child's doubt about something the prepared material does not cover) and seeing it would help more than words. It takes up to a minute to be drawn,
    so say aloud that you are drawing it and keep explaining in words; you are told when it is ready, then show it with show_screen. A class has room for 6 of these. Describe ONE frozen moment in which the idea is visible (who or what is doing what, with its visible effect), never text or arrows.

    Args:
        description: concrete English description of the scene, at most 40 words.
        caption: at most 4 Hindi words naming what it shows.
    """
    turn, room = _room()
    if room and room.drawn >= MAX_DRAWN_IN_CLASS:
        return {"status": "error", "error": "you already drew the most pictures allowed in this class. Make a figure with draw_html instead (a labelled diagram, steps or comparison), or use the catalog"}
    if room:
        room.drawn += 1
    code = room.code if room else turn.session_id
    name = tutor._new_id("pd").replace("-", "_")
    tutor._push({"type": "thinking", "text": "🎨 चित्र बन रहा है…"})

    async def work() -> None:
        try:
            res = await picturegen.draw(description[:300], WEB_PUBLIC / "chat" / f"class-{code}" / f"{name}.webp", prepare.LIVE_STYLE)
        except Exception as e:  # noqa: BLE001
            res = {"status": "error", "error": repr(e)[:200]}
        tutor._push({"type": "thinking", "text": ""})
        log.info("draw-picture-done", room=code, name=name, status=res.get("status"), error=res.get("error", ""), seconds=res.get("seconds", ""))
        if res.get("status") == "ok":
            turn.lesson_pictures[name] = f"/chat/class-{code}/{name}.webp"
            if room:
                room.catalog[name] = {"caption": caption.strip()[:40], "shows": description[:200]}
                room.ready_new[name] = 0
            await _announce(room, f"(The picture you asked for is ready: {name} — {description[:200]}. Show it with show_screen when it fits.)")
        else:
            if room:
                room.drawn -= 1  # a failed picture does not use up the class's allowance
            await _announce(room, f"(The picture «{description[:80]}» could NOT be drawn ({str(res.get('error', 'the image service refused or was busy'))[:80]}). Do not wait for it. Make a figure with draw_html instead (labelled parts, steps or cause and effect), or use a catalog item, and keep explaining.)")

    asyncio.create_task(work())  # keeps the ContextVar (the Turn) of this call
    return {"status": "started", "note": "you will be told when it is ready; keep teaching"}


async def draw_html(description: str, caption: str = "") -> dict:
    """Write a NEW figure (a labelled diagram, table, scale, cause -> effect boxes, steps in order, small animation) when no catalog figure shows what you need and a figure would make it clearer than a picture or words. It takes 15-30 seconds,
    so say aloud that you are drawing it and keep explaining in words; you are told when it is ready, then show it with show_screen. A class has room for 8 of these.

    Args:
        description: English instruction to the figure writer: which Hindi labels to show and how they are arranged (3-6 elements), at most 70 words. No drawings of objects or people, no diagonal lines.
        caption: at most 4 Hindi words.
    """
    turn, room = _room()
    if room and room.figs_drawn >= MAX_FIGS_IN_CLASS:
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
            room.ready_new[name] = 0
            await _announce(room, f"(The figure you asked for is ready: {name} — {description[:200]}. Show it with show_screen when it fits.)")
        elif room:
            room.figs_drawn -= 1  # a failed figure does not use up the allowance
            await _announce(room, f"(The figure «{description[:80]}» could NOT be made ({'; '.join(problems)[:100]}). Do not wait for it. Try once more with a simpler description (fewer elements), or use a catalog item, and keep explaining in words.)")

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
        room.catalog.update({k: {"caption": v["caption"], "shows": v.get("shows") or v.get("description", "")} for k, v in r["pictures"].items()})
    return {"status": "ok", "class_notes": r["notes"], "suggested_steps": r["steps"], "catalog": r["catalog"]}


async def finish_class() -> dict:
    """Call this once, after the recap and the home activity have been spoken: the class is over and the children may now talk freely with you."""
    _, room = _room()
    if room:
        room.finished = True
        await room.broadcast(room.public_state())
    log.info("class-finished", room=room.code if room else "")
    return {"status": "ok", "now": "Invite the children to ask anything about today's lesson. From now on answer their questions one at a time exactly as in the section DOUBT HANDLING: the same care as in the class, voice and picture together. No new steps."}


TOOLS = [tutor.plan, show_screen, wait_for_answer, draw_picture, draw_html, prepare_class, finish_class]
BLOCKING = {"prepare_class", "plan", "wait_for_answer"}  # the model waits for these (and then goes on speaking by itself); everything else runs while she keeps talking, answered SILENT
