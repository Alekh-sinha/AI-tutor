"""Teacher dashboard API.
  chapters:  list chapters/lessons with status; upload a book PDF (parse + plan as a background job); GENERATE a lesson video (background job)
  review:    view a lesson's lecture, edit it by chat (editing agent on a working copy), accept / reject each change (every accepted change is a saved
             version with undo), run the full reviewers, PUBLISH (rebuilds the video; blocked until the code checks pass and no change is pending)
Every request carries `chapter` (default: the first chapter). Auth: set TEACHER_TOKEN and send it in the `x-teacher-token` header (unset = development mode).
Logs: logs/teacher.jsonl (edit requests, proposals, accept/reject/undo, publish) and logs/content.jsonl (generation jobs)."""

import asyncio
import base64
import difflib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from google.adk.agents import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.access import credits, ownership, usage
from ai_teacher_api.authoring import edit_loop
from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.authoring.review import lecture_checks, lecture_images
from ai_teacher_api.common import logsetup, workspace
from ai_teacher_api.common.paths import DATA_DIR, DEFAULT_CHAPTER, NAME, chapter_dir, public_id
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, DEFAULT_VOICE, WEB_PUBLIC
from ai_teacher_api.content.brief import LessonBrief, render
from ai_teacher_api.director import run_direct
from ai_teacher_api.safety import gate
from ai_teacher_api.teacher import jobs, publishing
from ai_teacher_api.teacher.agent import ASKED, build_teacher_editor

log = logsetup.get("teacher")
ILLUSTRATED = DATA_DIR  # served at /files/<chapter>/illustrated/<lesson>-final/...
MAX_USER_CHAPTERS = 5
MIN_LESSON_USD = 3.0  # balance needed to start building a lesson video (a build costs roughly this much)
WIDE_LINES, WIDE_PICTURES = 0.35, 4  # a change touching more than this share of the lecture's lines, or this many pictures, needs a second confirmation
LABELS = {"view_picture": "चित्र देख रहा हूँ…", "edit_image": "चित्र बदल रहा हूँ…", "generate_image": "नया चित्र बना रहा हूँ…", "replace_text": "पाठ बदल रहा हूँ…", "ask_teacher": ""}

router = APIRouter(prefix="/teacher")
_sessions = InMemorySessionService()
_publish: dict[str, dict] = {}


def auth(x_teacher_token: str | None = Header(None)) -> None:
    token = os.environ.get("TEACHER_TOKEN")
    if token and x_teacher_token != token:
        raise HTTPException(401, "teacher token required")


# ---------------------------------------------------------------- helpers
def _dir(lesson: str, chapter: str) -> Path:
    if not NAME.match(lesson):
        raise HTTPException(400, "bad lesson id")
    d = chapter_dir(chapter) / "illustrated" / f"{lesson}-final"
    if not (d / "lecture.md").exists():
        raise HTTPException(404, "no lecture for this lesson yet")
    return d


def _versions(d: Path) -> list[int]:
    return sorted(int(p.name[1:]) for p in (d / "versions-saved").glob("v*") if p.name[1:].isdigit()) if (d / "versions-saved").exists() else []


def _snapshot(d: Path, note: str) -> int:
    n = (_versions(d) or [0])[-1] + 1
    v = d / "versions-saved" / f"v{n}"
    v.mkdir(parents=True)
    shutil.copy(d / "lecture.md", v / "lecture.md")
    for f in d.glob("*.webp"):
        shutil.copy(f, v / f.name)
    (v / "note.txt").write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {note}")
    return n


def _outline(lesson: str, chapter: str) -> dict:
    plan = json.loads((chapter_dir(chapter) / "plan.json").read_text())
    try:
        return next(l for l in plan["lessons"] if l["id"] == lesson)
    except StopIteration:
        raise HTTPException(404, "lesson not in the plan") from None


def _concepts(lesson: str, chapter: str) -> int:
    return len(_outline(lesson, chapter)["beats"])


def _book_points(lesson: str, chapter: str) -> str:
    f = chapter_dir(chapter) / f"brief-{lesson}.json"
    return render(LessonBrief.model_validate_json(f.read_text())) if f.exists() else ""


def _pending(d: Path) -> list[str]:
    return sorted(p.name for p in (d / "proposals").glob("*") if (p / "lecture.md").exists()) if (d / "proposals").exists() else []


def _script_json(chapter: str, pid: str) -> str | None:
    f = chapter_dir(chapter) / f"directed-{pid}.json"
    return f.read_text() if f.exists() else None


def _view(lesson: str, chapter: str) -> dict:
    d = _dir(lesson, chapter)
    md = (d / "lecture.md").read_text()
    return {
        "chapter": chapter, "lesson": lesson, "markdown": md, "base_url": f"/api/files/{chapter}/illustrated/{lesson}-final/",
        "pictures": [{"name": n, "description": desc} for desc, n in lecture_images(md)],
        "checks": lecture_checks(md, d, _concepts(lesson, chapter)),
        "versions": _versions(d), "pending": _pending(d), "published": (WEB_PUBLIC / "lessons" / f"{public_id(chapter, lesson)}.json").exists(),
        "public_id": public_id(chapter, lesson),
        "publish": publishing.status(chapter_dir(chapter), public_id(chapter, lesson), md, _script_json(chapter, public_id(chapter, lesson))),
    }


# ---------------------------------------------------------------- chapters and generation
def _book_name(d, fallback: str) -> str:
    """Chapters planned before the plan stored the name: take it from chapter.json (what the teacher typed at upload)."""
    try:
        return json.loads((d / "chapter.json").read_text()).get("book") or fallback
    except (OSError, ValueError):
        return fallback


@router.get("/chapters", dependencies=[Depends(auth)])
def chapters() -> list[dict]:
    out = []
    for p in sorted(DATA_DIR.glob("*/plan.json")):
        c = p.parent.name
        u = usage.current()
        if not ownership.can_access(c, u["email"] if u else None):
            continue
        plan = json.loads(p.read_text())
        lessons = []
        for l in plan["lessons"]:
            f = p.parent / "illustrated" / f"{l['id']}-final"
            pid = public_id(c, l["id"])
            has_lecture = (f / "lecture.md").exists()
            pub = publishing.status(p.parent, pid, (f / "lecture.md").read_text() if has_lecture else "", _script_json(c, pid)) if has_lecture else {"live": False, "version": 0, "lecture_changed": False, "video_changed": False, "draft_ready": False}
            lessons.append({"id": l["id"], "title": l["title"], "has_lecture": has_lecture, "has_video": (WEB_PUBLIC / "lessons" / f"{pid}.json").exists(),
                            "public_id": pid, "pending": len(_pending(f)) if f.exists() else 0, "live": pub["live"], "version": pub["version"],
                            "draft": pub["lecture_changed"] or pub["video_changed"], "lecture_changed": pub["lecture_changed"], "video_changed": pub["video_changed"]})
        out.append({"id": c, "book": plan.get("book") or _book_name(p.parent, c), "lessons": lessons})
    return out


@router.post("/chapters", dependencies=[Depends(auth)])
async def upload_chapter(chapter: str = Form(...), book: str = Form(...), pdf: UploadFile = File(...)) -> dict:
    """Upload a book chapter PDF: parse it and plan its lessons (a background job). The lessons are then generated one by one from the dashboard."""
    chapter = chapter.strip()
    u = usage.current()
    if ownership.restricted() and u and not credits.is_admin(u["email"]):
        chapter = ownership.prefix_for(u["email"]) + chapter[:28]  # a user's chapters carry their prefix: that is how ownership is known
        if len([p for p in DATA_DIR.glob(ownership.prefix_for(u["email"]) + "*")]) >= MAX_USER_CHAPTERS:
            raise HTTPException(409, f"You can keep up to {MAX_USER_CHAPTERS} chapters. Please ask the admin if you need more.")
    await asyncio.to_thread(credits.check, u["email"]) if u else None
    if not NAME.match(chapter):
        raise HTTPException(422, "अध्याय का नाम सिर्फ़ अंग्रेज़ी अक्षर, अंक, - या _ में हो (बिना स्पेस, अधिकतम 40), जैसे ch7")
    if (DATA_DIR / chapter).exists():
        raise HTTPException(409, f"'{chapter}' नाम पहले से है — कोई दूसरा नाम चुनिए (जैसे {chapter}-2)")
    data = await pdf.read()
    if len(data) > 40_000_000 or not data.startswith(b"%PDF"):
        raise HTTPException(400, "a PDF of at most 40 MB is required")
    d = DATA_DIR / chapter
    d.mkdir(parents=True)
    (d / "source.pdf").write_bytes(data)
    log.info("chapter-upload", chapter=chapter, book=book, bytes=len(data))

    def work(progress) -> dict:
        from ai_teacher_api.content import chapter as parse
        from ai_teacher_api.content import run_plan

        progress("parsing the PDF")
        ch = parse.parse_chapter(d / "source.pdf", book)
        (d / "chapter.json").write_text(json.dumps(ch.model_dump(), ensure_ascii=False, indent=2) + "\n")
        progress("planning the lessons")
        pages = run_plan.run(d / "chapter.json", d / "plan.json", DEFAULT_TEXT_MODEL, "hi-IN", "Bihar", 6)
        plan = json.loads((d / "plan.json").read_text())
        plan["book"] = book  # the name the teacher typed (the planner does not store it)
        (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        return {"lessons": len(plan["lessons"]), **pages}

    try:
        job = jobs.start("plan", f"chapter {chapter}", work, needs_images=False)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return job


@router.post("/lesson/{lesson}/generate", dependencies=[Depends(auth)])
def generate(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    """Generate the lesson: Agent 1 (lecture + pictures) -> reviewers + editor -> Agent 2 (video script + voice). Takes about 20-30 minutes; poll /teacher/jobs/<id>."""
    from ai_teacher_api.content import run_lesson

    d = chapter_dir(chapter)
    _outline(lesson, chapter)
    u = usage.current()
    if u:
        credits.check(u["email"])
        me = credits.get(u["email"])
        if me and me["role"] != "admin" and credits.balance_micro(me) < round(MIN_LESSON_USD * credits.M):
            raise credits.CreditExhausted(f"Building a lesson needs about ${MIN_LESSON_USD:.0f} of credit. You have ${credits.balance_micro(me) / credits.M:.2f}. You can ask for more credit.")
    if (d / "illustrated" / f"{lesson}-final" / "lecture.md").exists():
        raise HTTPException(409, "this lesson already has a lecture: edit it, or publish it")
    pid = public_id(chapter, lesson)

    def work(progress) -> dict:
        r = run_lesson.run(d, lesson, voice=DEFAULT_VOICE, out_id=pid, progress=progress)
        return {"public_id": pid, "left_for_teacher": r.get("direct", {}).get("for_teacher", [])}

    try:
        job = jobs.start("generate", f"{chapter}/{lesson}", work)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return job


@router.get("/jobs", dependencies=[Depends(auth)])
def running_jobs() -> list[dict]:
    """Jobs still running (the dashboard shows them again after a page refresh)."""
    u = usage.current()
    mine = [j for j in jobs.running() if not ownership.restricted() or (u and (credits.is_admin(u["email"]) or j.get("owner") == u["email"]))]
    return [{**j, "elapsed": round(time.time() - j["started"])} for j in mine]


@router.get("/jobs/{jid}", dependencies=[Depends(auth)])
def job_status(jid: str) -> dict:
    j = jobs.get(jid)
    u = usage.current()
    if not j or (ownership.restricted() and not (u and (credits.is_admin(u["email"]) or j.get("owner") == u["email"]))):
        raise HTTPException(404, "unknown job")
    return {**j, "elapsed": round((j["ended"] or time.time()) - j["started"])}


# ---------------------------------------------------------------- review and edit one lesson
@router.get("/lessons", dependencies=[Depends(auth)])
def lessons(chapter: str = DEFAULT_CHAPTER) -> list[dict]:
    base = chapter_dir(chapter) / "illustrated"
    return [{"lesson": p.name.removesuffix("-final"), "pending": len(_pending(p))} for p in sorted(base.glob("*-final")) if (p / "lecture.md").exists()]


@router.get("/lesson/{lesson}", dependencies=[Depends(auth)])
def lesson_view(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    return _view(lesson, chapter)


class EditIn(BaseModel):
    instruction: str = Field(default="", max_length=1500)
    selection: str = Field(default="", max_length=1500, description="passage text or 'picture:<name>' the teacher selected")
    audio_b64: str | None = Field(default=None, max_length=1_500_000)
    audio_mime: str = "audio/wav"
    image_b64: str | None = Field(default=None, max_length=2_000_000)
    image_mime: str = "image/jpeg"


def _paragraphs(md: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", md) if p.strip()]


def _diff(before: str, after: str) -> list[dict]:
    a, b = _paragraphs(before), _paragraphs(after)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append({"before": "\n\n".join(a[i1:i2]), "after": "\n\n".join(b[j1:j2])})
    return out


def _sha(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


async def _edit_run(lesson: str, chapter: str, body: EditIn, queue: asyncio.Queue) -> None:
    d = _dir(lesson, chapter)
    pid = uuid.uuid4().hex[:8]
    work = d / "proposals" / pid
    t0 = time.time()
    if not workspace.try_acquire(f"teacher edit {chapter}/{lesson}"):
        log.warn("edit-busy", lesson=lesson, holder=workspace.holder["who"])
        queue.put_nowait({"type": "error", "text": "अभी दूसरा काम चल रहा है, थोड़ी देर बाद कोशिश कीजिए।"})
        queue.put_nowait({"type": "done"})
        return
    tools: dict[str, int] = {}
    try:
        shutil.copytree(d, work, ignore=shutil.ignore_patterns("proposals", "versions-saved", "versions", "audit-*", "*.jsonl", "*.json"))
        ill.configure(work, ill.IMAGE_MODEL)
        ill.set_redraw_allowed(None)
        ill.set_budget(8)
        md = (work / "lecture.md").read_text()
        edit_loop._doc["md"] = md
        asked: list[str] = []
        ASKED.set(asked)
        text = f"BOOK POINTS:\n{_book_points(lesson, chapter)}\n\nPictures that exist: {sorted(p.stem for p in work.glob('*.webp'))}\n\nTHE LECTURE:\n{md}\n\n"
        if body.selection:
            text += f"THE TEACHER SELECTED: {body.selection}\n\n"
        text += f"TEACHER'S INSTRUCTION: {body.instruction}" if body.instruction.strip() else "The teacher's instruction is in the attachment."
        parts = [types.Part(text=text)]
        if body.audio_b64:
            parts.append(types.Part.from_bytes(data=base64.b64decode(body.audio_b64), mime_type=body.audio_mime))
        if body.image_b64:
            parts.append(types.Part.from_bytes(data=base64.b64decode(body.image_b64), mime_type=body.image_mime))
        sid = uuid.uuid4().hex
        await _sessions.create_session(app_name="ai-teacher-editor", user_id="teacher", session_id=sid)
        runner = Runner(agent=build_teacher_editor(), app_name="ai-teacher-editor", session_service=_sessions)
        reply = ""
        async for e in runner.run_async(user_id="teacher", session_id=sid, new_message=types.Content(role="user", parts=parts), run_config=RunConfig(max_llm_calls=30)):
            for c in e.get_function_calls():
                tools[c.name] = tools.get(c.name, 0) + 1
                if LABELS.get(c.name):
                    queue.put_nowait({"type": "thinking", "text": LABELS[c.name]})
            for p in (e.content.parts if e.content else []):
                if p.thought and p.text:
                    queue.put_nowait({"type": "thought", "text": p.text.strip()[:600]})
                elif p.text and e.is_final_response() and not e.get_function_calls():
                    reply += p.text
        new_md = edit_loop._doc["md"]
        changed_pics = sorted(f.stem for f in work.glob("*.webp") if not (d / f.name).exists() or _sha(f) != _sha(d / f.name))
        diff = _diff(md, new_md)
        outcome = "question" if asked else ("no-change" if not diff and not changed_pics else "proposal")
        if asked:
            shutil.rmtree(work, ignore_errors=True)
            queue.put_nowait({"type": "question", "text": asked[0]})
        elif outcome == "no-change":
            shutil.rmtree(work, ignore_errors=True)
            queue.put_nowait({"type": "reply", "text": reply or "कोई बदलाव नहीं किया।"})
        else:
            (work / "lecture.md").write_text(new_md)
            share = sum(len(x["before"].splitlines()) + len(x["after"].splitlines()) for x in diff) / max(1, 2 * len(md.splitlines()))
            wide = share > WIDE_LINES or len(changed_pics) > WIDE_PICTURES
            (work / "meta.json").write_text(json.dumps({"instruction": body.instruction, "changed_pictures": changed_pics}))
            queue.put_nowait({"type": "proposal", "id": pid, "reply": reply, "diff": diff, "changed_pictures": changed_pics, "wide": wide,
                              "base_url": f"/api/files/{chapter}/illustrated/{lesson}-final/proposals/{pid}/", "checks": lecture_checks(new_md, work, _concepts(lesson, chapter))})
        log.info("edit", chapter=chapter, lesson=lesson, instruction=body.instruction[:300], selection=body.selection[:120], outcome=outcome, tools=tools,
                 changed_pictures=changed_pics, diff_paragraphs=len(diff), question=asked[0] if asked else "", reply=reply[:300], seconds=round(time.time() - t0, 1))
    except Exception as ex:  # noqa: BLE001
        shutil.rmtree(work, ignore_errors=True)
        log.error("edit-failed", chapter=chapter, lesson=lesson, error=repr(ex)[:400])
        queue.put_nowait({"type": "error", "text": "बदलाव नहीं हो सका।", "detail": repr(ex)[:200]})
    finally:
        workspace.release()
        queue.put_nowait({"type": "done"})


@router.post("/lesson/{lesson}/edit", dependencies=[Depends(auth)])
async def edit(lesson: str, body: EditIn, chapter: str = DEFAULT_CHAPTER) -> StreamingResponse:
    _dir(lesson, chapter)
    if not (body.instruction.strip() or body.audio_b64 or body.image_b64):
        raise HTTPException(400, "empty instruction")
    verdict = await gate.screen(body.instruction, "teacher-edit")  # the editor may not be used to bring unsafe content into a children's lesson
    if not verdict.ok:
        raise HTTPException(422, {"code": "unsafe", "message": verdict.message_en, "message_hi": verdict.message_hi})
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_edit_run(lesson, chapter, body, q))

    async def stream():
        try:
            async for chunk in sse.events(q, 600):
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/lesson/{lesson}/accept/{pid}", dependencies=[Depends(auth)])
def accept(lesson: str, pid: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    d = _dir(lesson, chapter)
    work = d / "proposals" / re.sub(r"[^a-f0-9]", "", pid)
    if not (work / "lecture.md").exists():
        raise HTTPException(404, "no such proposal")
    meta = json.loads((work / "meta.json").read_text()) if (work / "meta.json").exists() else {}
    n = _snapshot(d, f"before: {meta.get('instruction', '')[:80]}")  # the state we are leaving, so undo returns to it
    shutil.copy(work / "lecture.md", d / "lecture.md")
    for f in work.glob("*.webp"):
        if not (d / f.name).exists() or _sha(f) != _sha(d / f.name):
            shutil.copy(f, d / f.name)
    shutil.rmtree(work)
    log.info("accept", chapter=chapter, lesson=lesson, proposal=pid, snapshot=n, instruction=meta.get("instruction", "")[:200])
    return _view(lesson, chapter)


@router.post("/lesson/{lesson}/reject/{pid}", dependencies=[Depends(auth)])
def reject(lesson: str, pid: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    d = _dir(lesson, chapter)
    shutil.rmtree(d / "proposals" / re.sub(r"[^a-f0-9]", "", pid), ignore_errors=True)
    log.info("reject", chapter=chapter, lesson=lesson, proposal=pid)
    return _view(lesson, chapter)


@router.post("/lesson/{lesson}/undo", dependencies=[Depends(auth)])
def undo(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    d = _dir(lesson, chapter)
    vs = _versions(d)
    if not vs:
        raise HTTPException(409, "nothing to undo")
    v = d / "versions-saved" / f"v{vs[-1]}"
    shutil.copy(v / "lecture.md", d / "lecture.md")
    for f in v.glob("*.webp"):
        shutil.copy(f, d / f.name)
    shutil.rmtree(v)  # the snapshot is consumed: undo again goes one step further back
    log.info("undo", chapter=chapter, lesson=lesson, snapshot=vs[-1])
    return _view(lesson, chapter)


@router.post("/lesson/{lesson}/review", dependencies=[Depends(auth)])
async def review_now(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    """Run the full reviewers (strong model, several passes; takes a few minutes) and return what they find."""
    d = _dir(lesson, chapter)
    md = (d / "lecture.md").read_text()
    t0 = time.time()
    found = await edit_loop.review_lecture(md, _book_points(lesson, chapter), d, f"teacher-{int(time.time())}", _concepts(lesson, chapter))
    log.info("review", chapter=chapter, lesson=lesson, findings=found.lines(), doubtful=found.doubtful, seconds=round(time.time() - t0))
    return {"findings": found.lines(), "doubtful": found.doubtful}


@router.post("/lesson/{lesson}/archive-unused", dependencies=[Depends(auth)])
def archive_unused_pictures(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    """Move pictures that the lecture does not use into `unused/` (nothing is deleted)."""
    d = _dir(lesson, chapter)
    moved = edit_loop.archive_unused(d, (d / "lecture.md").read_text())
    log.info("archive-unused", chapter=chapter, lesson=lesson, pictures=moved)
    return _view(lesson, chapter)


class PublishIn(BaseModel):
    approved_by_teacher: bool = False


@router.post("/lesson/{lesson}/publish", dependencies=[Depends(auth)])
async def publish(lesson: str, body: PublishIn, chapter: str = DEFAULT_CHAPTER) -> dict:
    d = _dir(lesson, chapter)
    if not body.approved_by_teacher:
        raise HTTPException(409, "the teacher must approve before publishing")
    if _pending(d):
        raise HTTPException(409, "accept or reject the pending changes first")
    problems = _view(lesson, chapter)["checks"]
    if problems:
        raise HTTPException(409, {"checks": problems})
    pid = public_id(chapter, lesson)
    d_chapter = chapter_dir(chapter)
    key = f"{chapter}/{lesson}"
    if _publish.get(key, {}).get("status") == "running":
        raise HTTPException(409, "already publishing")
    _publish[key] = {"status": "running", "started": time.time()}
    log.info("publish-start", chapter=chapter, lesson=lesson, public_id=pid)

    async def job() -> None:
        try:
            res = await asyncio.to_thread(run_direct.run, chapter_dir(chapter), lesson, DEFAULT_TEXT_MODEL, DEFAULT_VOICE, d, pid, True, True)
            run_direct.register(pid, json.loads((WEB_PUBLIC / "lessons" / f"{pid}.json").read_text())["title"], res.get("duration", 0), "published")
            publishing.mark_published(d_chapter, pid, (d / "lecture.md").read_text(), (d_chapter / f"directed-{pid}.json").read_text())
            _publish[key] = {"status": "done", "public_id": pid, "left_for_teacher": res["for_teacher"]}
            log.info("publish-done", chapter=chapter, lesson=lesson, public_id=pid, left=res["for_teacher"])
        except Exception as ex:  # noqa: BLE001
            _publish[key] = {"status": "failed", "error": repr(ex)[:300]}
            log.error("publish-failed", chapter=chapter, lesson=lesson, error=repr(ex)[:400])

    asyncio.create_task(job())
    return {"status": "running"}


@router.get("/lesson/{lesson}/publish-status", dependencies=[Depends(auth)])
def publish_status(lesson: str, chapter: str = DEFAULT_CHAPTER) -> dict:
    return _publish.get(f"{chapter}/{lesson}", {"status": "idle"})
