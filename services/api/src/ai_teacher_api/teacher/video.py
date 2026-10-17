"""Edit the BUILT VIDEO by chat (no director call): the teacher changes what is said, a caption, a note, a scene break; the editing agent changes the directed script
(`data/<chapter>/directed-<id>.json`), the teacher sees the storyboard difference, accepts or rejects; an accepted change rebuilds only the voice + assembly (about a minute) and keeps a version for undo.
The lecture-level editor (routes.py) changes the lesson text/pictures; this one changes the video that was made from it.
Logs: logs/teacher.jsonl (`video-edit`, `video-accept`, `video-undo`, `video-rebuild`)."""

import asyncio
import contextvars
import difflib
import json
import re
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.adk.agents import LlmAgent, RunConfig
from google.adk.planners import BuiltInPlanner
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.paths import DEFAULT_CHAPTER, chapter_dir, public_id
from ai_teacher_api.common.settings import DEFAULT_VOICE, resolve_model
from ai_teacher_api.director import run_direct
from ai_teacher_api.director.agent import Directed
from ai_teacher_api.director.script import BoardCue
from ai_teacher_api.teacher import jobs
from ai_teacher_api.teacher.agent import ASKED, ask_teacher
from ai_teacher_api.teacher.routes import auth

log = logsetup.get("teacher")
router = APIRouter(prefix="/teacher/lesson/{lesson}/video")
WORK: contextvars.ContextVar[Directed] = contextvars.ContextVar("video_work")
_sessions = InMemorySessionService()
WIDE_LINES = 0.3  # more than this share of the spoken lines changed = a wide change (needs the second confirmation)


# ---------------------------------------------------------------- the storyboard view
def storyboard(directed: Directed) -> list[dict]:
    out = []
    for i, line in enumerate(directed.script.lines):
        cues = [{"kind": c.kind, "id": c.id, "text": c.text or c.description or "", "target": c.target, "effect": c.effect} for c in line.cues]
        out.append({"i": i, "text": line.text, "cues": cues})
    return out


def _flat(sb: list[dict]) -> list[str]:
    def cue(c):
        return c["kind"] + (f"#{c['id']}" if c["id"] else "") + (f" '{c['text']}'" if c["text"] and c["kind"] in ("note", "image", "choice") else "") + (f" -> {c['target']}" if c["target"] else "")
    return [f"{x['text']}  ||  " + ", ".join(cue(c) for c in x["cues"]) for x in sb]


def diff_lines(before: Directed, after: Directed) -> list[dict]:
    a, b = _flat(storyboard(before)), _flat(storyboard(after))
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append({"line": i1 if tag != "insert" else j1, "before": "\n".join(a[i1:i2]), "after": "\n".join(b[j1:j2])})
    return out


def agent_view(directed: Directed) -> str:
    return "\n".join(f"[{x['i']}] {x['text']}" + "".join(f"\n      {c['kind']} id={c['id']} {c['text']}".rstrip() + (f" target={c['target']}" if c["target"] else "") for c in x["cues"]) for x in storyboard(directed))


# ---------------------------------------------------------------- tools of the video-editing agent (they change the working copy in WORK)
async def replace_line(index: int, text: str) -> dict:
    """Change what the teacher SAYS in one line (index as shown). Keep it one or two short sentences in Hindi; the voice for the whole video is re-recorded after the teacher accepts.

    Args:
        index: the line number in square brackets.
        text: the new spoken text.
    """
    d = WORK.get()
    if not (0 <= index < len(d.script.lines)) or not text.strip():
        return {"status": "error", "error": "bad index or empty text"}
    d.script.lines[index].text = text.strip()
    return {"status": "ok"}


def _cue(cue_id: str) -> BoardCue | None:
    return next((c for l in WORK.get().script.lines for c in l.cues if c.id == cue_id), None)


async def set_caption(image_id: str, caption: str) -> dict:
    """Change the caption written under a picture (at most 4 Hindi words naming what it shows).

    Args:
        image_id: the picture's id (the id= value of its image cue).
        caption: the new caption.
    """
    c = _cue(image_id)
    if c is None or c.kind != "image":
        return {"status": "error", "error": "no such picture id"}
    c.text = caption.strip()[:40]
    return {"status": "ok"}


async def edit_note(note_id: str, text: str) -> dict:
    """Change the words of a blackboard note (at most 6 words).

    Args:
        note_id: the note's id.
        text: the new words.
    """
    c = _cue(note_id)
    if c is None or c.kind != "note":
        return {"status": "error", "error": "no such note id"}
    c.text = text.strip()[:60]
    return {"status": "ok"}


async def remove_cue(cue_id: str) -> dict:
    """Remove a note or an animation from the board (not pictures or question cards: those belong to the lesson text).

    Args:
        cue_id: the id of a note, or of an animation's target when the id of the animation itself is empty.
    """
    d = WORK.get()
    for l in d.script.lines:
        for c in l.cues:
            if c.id == cue_id and c.kind == "note":
                l.cues.remove(c)
                l.cues = [x for x in l.cues if x.target != cue_id]
                for m in d.script.lines:
                    m.cues = [x for x in m.cues if x.target != cue_id]
                return {"status": "ok"}
    return {"status": "error", "error": "only notes can be removed (use the lecture editor for pictures and questions)"}


async def add_note(line_index: int, text: str, style: str = "bullet") -> dict:
    """Write a new note on the board when the given line starts.

    Args:
        line_index: the line number in square brackets.
        text: at most 6 words, Hindi.
        style: "heading", "body", "bullet" or "key".
    """
    d = WORK.get()
    if not (0 <= line_index < len(d.script.lines)) or not text.strip():
        return {"status": "error", "error": "bad line or empty text"}
    used = {c.id for l in d.script.lines for c in l.cues if c.id}
    nid = f"t{line_index}_{len(used)}"
    d.script.lines[line_index].cues.append(BoardCue(kind="note", id=nid, text=text.strip()[:60], style=style if style in ("heading", "body", "bullet", "key") else "bullet"))
    return {"status": "ok", "id": nid}


async def set_scene_break(line_index: int, on: bool) -> dict:
    """Start a new scene at a line (the board is cleared and the first items of that line appear), or remove such a break.

    Args:
        line_index: the line number.
        on: True to add the break, False to remove it.
    """
    d = WORK.get()
    if not (0 <= line_index < len(d.script.lines)):
        return {"status": "error", "error": "bad line"}
    cues = d.script.lines[line_index].cues
    has = any(c.kind == "clear" for c in cues)
    if on and not has:
        cues.insert(0, BoardCue(kind="clear"))
    if not on:
        d.script.lines[line_index].cues = [c for c in cues if c.kind != "clear"]
    return {"status": "ok"}


INSTRUCTION = """You are the video-editing assistant of a teacher who is reviewing a finished classroom video (a script of numbered spoken lines, each with the board items that appear at that line).
The teacher says, in Hindi or English (typed, spoken or with a photo), what to change. Do exactly that with your tools and keep everything else; then reply in one or two sentences, in the
teacher's language, saying what you changed. Tools: replace_line, set_caption, edit_note, remove_cue (notes only), add_note, set_scene_break; ask_teacher(question) when the request is wide
(touches many lines or changes what is taught) or ambiguous: then make NO edits. Facts must stay consistent with the BOOK POINTS; if the request contradicts them, ask first. Pictures and
question cards belong to the lesson text: if the teacher wants those changed, tell them to use the lesson editor."""


def build_video_editor(model: str | None = None) -> LlmAgent:
    return LlmAgent(name="video_editor", model=resolve_model(model), instruction=INSTRUCTION, tools=[replace_line, set_caption, edit_note, remove_cue, add_note, set_scene_break, ask_teacher],
                    planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)))


# ---------------------------------------------------------------- storage helpers
def _paths(lesson: str, chapter: str):
    d = chapter_dir(chapter)
    pid = public_id(chapter, lesson)
    return d, pid, d / f"directed-{pid}.json", d / "directed-versions" / pid, d / "video-proposals"


def _load(lesson: str, chapter: str) -> Directed:
    _, _, f, _, _ = _paths(lesson, chapter)
    if not f.exists():
        raise HTTPException(404, "this lesson has no video yet: generate it first")
    return Directed.model_validate_json(f.read_text())


def _checks(lesson: str, chapter: str, directed: Directed) -> list[str]:
    d = chapter_dir(chapter)
    plan = json.loads((d / "plan.json").read_text())
    concepts = len(next(l for l in plan["lessons"] if l["id"] == lesson)["beats"])
    md = (d / "illustrated" / f"{lesson}-final" / "lecture.md").read_text()
    return run_direct.checks(md, directed.script, concepts)


def _rebuild(lesson: str, chapter: str) -> dict:
    d, pid, saved, _, _ = _paths(lesson, chapter)
    src = d / "illustrated" / f"{lesson}-final"
    directed = Directed.model_validate_json(saved.read_text())

    def work(progress) -> dict:
        t0 = time.time()
        progress("recording the voice and assembling the video")
        r = run_direct.produce(d, lesson, pid, src, directed, (src / "lecture.md").read_text(), DEFAULT_VOICE)
        log.info("video-rebuild", chapter=chapter, lesson=lesson, seconds=round(time.time() - t0), **r)
        return r

    return jobs.start("video", f"{chapter}/{lesson} video", work, needs_images=False)


# ---------------------------------------------------------------- routes
@router.get("", dependencies=[Depends(auth)])
def view(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    directed = _load(lesson, chapter)
    _, pid, _, vdir, pdir = _paths(lesson, chapter)
    return {"public_id": pid, "lines": storyboard(directed), "checks": _checks(lesson, chapter, directed),
            "versions": sorted(int(p.stem[1:]) for p in vdir.glob("v*.json")) if vdir.exists() else [], "pending": sorted(p.stem for p in pdir.glob("*.json")) if pdir.exists() else []}


class VideoEditIn(BaseModel):
    instruction: str = Field(default="", max_length=1500)
    selection: str = Field(default="", max_length=600, description="e.g. 'line:12' or text the teacher selected")
    audio_b64: str | None = Field(default=None, max_length=1_500_000)
    audio_mime: str = "audio/wav"


async def _edit_run(lesson: str, chapter: str, body: VideoEditIn, queue: asyncio.Queue) -> None:
    import base64

    from ai_teacher_api.teacher.routes import _book_points

    t0, tools = time.time(), {}
    try:
        before = _load(lesson, chapter)
        work = before.model_copy(deep=True)
        WORK.set(work)
        asked: list[str] = []
        ASKED.set(asked)
        text = f"BOOK POINTS:\n{_book_points(lesson, chapter)}\n\nTHE VIDEO SCRIPT:\n{agent_view(before)}\n\n"
        if body.selection:
            text += f"THE TEACHER SELECTED: {body.selection}\n\n"
        text += f"TEACHER'S INSTRUCTION: {body.instruction}" if body.instruction.strip() else "The teacher's instruction is in the attachment."
        parts = [types.Part(text=text)]
        if body.audio_b64:
            parts.append(types.Part.from_bytes(data=base64.b64decode(body.audio_b64), mime_type=body.audio_mime))
        sid = uuid.uuid4().hex
        await _sessions.create_session(app_name="ai-teacher-video", user_id="teacher", session_id=sid)
        runner = Runner(agent=build_video_editor(), app_name="ai-teacher-video", session_service=_sessions)
        reply = ""
        async for e in runner.run_async(user_id="teacher", session_id=sid, new_message=types.Content(role="user", parts=parts), run_config=RunConfig(max_llm_calls=25)):
            for c in e.get_function_calls():
                tools[c.name] = tools.get(c.name, 0) + 1
                if c.name != "ask_teacher":
                    queue.put_nowait({"type": "thinking", "text": "वीडियो में बदलाव कर रहा हूँ…"})
            for p in (e.content.parts if e.content else []):
                if p.thought and p.text:
                    queue.put_nowait({"type": "thought", "text": p.text.strip()[:600]})
                elif p.text and e.is_final_response() and not e.get_function_calls():
                    reply += p.text
        diff = diff_lines(before, work)
        outcome = "question" if asked else ("no-change" if not diff else "proposal")
        if asked:
            queue.put_nowait({"type": "question", "text": asked[0]})
        elif not diff:
            queue.put_nowait({"type": "reply", "text": reply or "कोई बदलाव नहीं किया।"})
        else:
            d, _, _, _, pdir = _paths(lesson, chapter)
            pdir.mkdir(exist_ok=True)
            pid = uuid.uuid4().hex[:8]
            (pdir / f"{pid}.json").write_text(json.dumps({"instruction": body.instruction, "directed": work.model_dump()}, ensure_ascii=False))
            changed_lines = len({x["line"] for x in diff})
            queue.put_nowait({"type": "proposal", "id": pid, "reply": reply, "diff": diff, "wide": changed_lines / max(1, len(before.script.lines)) > WIDE_LINES,
                              "checks": _checks(lesson, chapter, work)})
        log.info("video-edit", chapter=chapter, lesson=lesson, instruction=body.instruction[:300], selection=body.selection[:100], outcome=outcome, tools=tools,
                 changed_blocks=len(diff), question=asked[0] if asked else "", reply=reply[:300], seconds=round(time.time() - t0, 1))
    except HTTPException as ex:
        queue.put_nowait({"type": "error", "text": str(ex.detail)})
    except Exception as ex:  # noqa: BLE001
        log.error("video-edit-failed", chapter=chapter, lesson=lesson, error=repr(ex)[:400])
        queue.put_nowait({"type": "error", "text": "बदलाव नहीं हो सका।", "detail": repr(ex)[:200]})
    finally:
        queue.put_nowait({"type": "done"})


@router.post("/edit", dependencies=[Depends(auth)])
async def edit(lesson: str, body: VideoEditIn, chapter: str = DEFAULT_CHAPTER) -> StreamingResponse:
    _load(lesson, chapter)
    if not (body.instruction.strip() or body.audio_b64):
        raise HTTPException(400, "empty instruction")
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_edit_run(lesson, chapter, body, q))

    async def stream():
        try:
            while True:
                ev = await asyncio.wait_for(q.get(), timeout=300)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] == "done":
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/accept/{pid}", dependencies=[Depends(auth)])
def accept(lesson: str, pid: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    d, public, saved, vdir, pdir = _paths(lesson, chapter)
    f = pdir / f"{re.sub(r'[^a-f0-9]', '', pid)}.json"
    if not f.exists():
        raise HTTPException(404, "no such proposal")
    prop = json.loads(f.read_text())
    vdir.mkdir(parents=True, exist_ok=True)
    n = (sorted(int(p.stem[1:]) for p in vdir.glob("v*.json")) or [0])[-1] + 1
    shutil.copy(saved, vdir / f"v{n}.json")  # the state we are leaving, so undo returns to it
    saved.write_text(json.dumps(prop["directed"], ensure_ascii=False, indent=1))
    f.unlink()
    try:
        job = _rebuild(lesson, chapter)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    log.info("video-accept", chapter=chapter, lesson=lesson, proposal=pid, snapshot=n, instruction=prop.get("instruction", "")[:200], job=job["id"])
    return job


@router.post("/reject/{pid}", dependencies=[Depends(auth)])
def reject(lesson: str, pid: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    _, _, _, _, pdir = _paths(lesson, chapter)
    (pdir / f"{re.sub(r'[^a-f0-9]', '', pid)}.json").unlink(missing_ok=True)
    return {"status": "rejected"}


@router.post("/undo", dependencies=[Depends(auth)])
def undo(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    d, public, saved, vdir, _ = _paths(lesson, chapter)
    vs = sorted(int(p.stem[1:]) for p in vdir.glob("v*.json")) if vdir.exists() else []
    if not vs:
        raise HTTPException(409, "nothing to undo")
    v = vdir / f"v{vs[-1]}.json"
    shutil.copy(v, saved)
    v.unlink()
    job = _rebuild(lesson, chapter)
    log.info("video-undo", chapter=chapter, lesson=lesson, snapshot=vs[-1], job=job["id"])
    return job
