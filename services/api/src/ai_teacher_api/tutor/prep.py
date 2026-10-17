"""Preparing a live class on a topic the child asked for (a topic that no recorded lesson covers). The teacher agent takes its time: it checks the facts with Google Search and writes class notes
(facts, steps with examples, picture ideas, check questions, misconceptions). The live teacher then teaches from those notes. Logged as `class-prepared` in logs/tutor.jsonl."""

import json
import re
import time

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.paths import DATA_DIR, split_public_id
from ai_teacher_api.common.settings import WEB_PUBLIC
from ai_teacher_api.content.brief import LessonBrief, render

log = logsetup.get("tutor")


def load_lesson(lesson_id: str) -> dict:
    return json.loads((WEB_PUBLIC / "lessons" / f"{lesson_id}.json").read_text())


def book_points(lesson_id: str) -> str:
    chapter, lesson = split_public_id(lesson_id)
    f = DATA_DIR / chapter / f"brief-{lesson}.json"
    return render(LessonBrief.model_validate_json(f.read_text())) if f.exists() else ""


def recorded_lessons() -> list[dict]:
    f = WEB_PUBLIC / "lessons" / "index.json"
    return [{"id": l["id"], "title": l["title"]} for l in json.loads(f.read_text())] if f.exists() else []


def pictures_of(lesson_ids: list[str]) -> dict[str, str]:
    """Pictures of the recorded lessons related to the child's topic: 'lesson/name' -> url."""
    out: dict[str, str] = {}
    for lid in lesson_ids:
        for e in load_lesson(lid)["events"]:
            if e["type"] == "image" and "~" not in e["id"]:
                out[f"{lid}/{e['id']}"] = e["src"]
    return out


INSTRUCTION = """You prepare a live class for a Class 6 child (11-12 years, Hindi-medium school, rural Bihar). The child said what they want to learn (in text, speech or a photo).
Check the facts with Google Search, then write class notes for the teacher in English, in this shape:
TOPIC: what exactly the child wants to learn (one line).
PREREQUISITES: what the child must already know (to check first with one question).
FACTS: 6-10 verified facts and definitions at Class 6 level, in the words of the Indian school books where you know them.
STEPS: 3-5 steps, one concept each. For each: a familiar everyday example from rural Bihar that you invent (not from a book), a picture idea (one still scene), and one check question with its answer.
MISCONCEPTIONS: 2-3 usual wrong ideas of children on this topic.
If the request is not a school topic, or is unsafe, write only: REFUSE: <short reason in Hindi, kind, offering to help with studies>.
The last line must be: RELATED: followed by the ids of the recorded lessons below that cover part of this topic (comma separated), or NONE."""


async def prepare(parts: list[types.Part], lessons: list[dict], model: str | None, session: str) -> dict:
    """Returns {"notes": text, "related": [lesson ids], "refused": reason or ""}."""
    catalog = "RECORDED LESSONS:\n" + "\n".join(f"- {l['id']}: {l['title']}" for l in lessons)

    async def run(m: str) -> str:
        agent = LlmAgent(name="class_prep", model=m, instruction=INSTRUCTION + "\n\n" + catalog, tools=[google_search])
        sessions = InMemorySessionService()
        runner = Runner(agent=agent, app_name="ai-teacher-prep", session_service=sessions)
        s = await sessions.create_session(app_name="ai-teacher-prep", user_id="student")
        out = ""
        async for e in runner.run_async(user_id="student", session_id=s.id, new_message=types.Content(role="user", parts=parts)):
            if e.is_final_response() and e.content:
                out += "".join(p.text or "" for p in e.content.parts if not p.thought)
        return out

    t0 = time.time()
    notes, used = await with_model_fallback(run, None)
    m = re.search(r"RELATED:\s*(.*)\s*$", notes.strip())
    known = {l["id"] for l in lessons}
    related = [x.strip() for x in (m.group(1).split(",") if m else []) if x.strip() in known]
    r = re.search(r"REFUSE:\s*(.+)", notes)
    out = {"notes": notes.strip(), "related": related, "refused": r.group(1).strip() if r else ""}
    log.info("class-prepared", session=session, model=used, seconds=round(time.time() - t0, 1), related=related, refused=out["refused"], notes=notes[:1500])
    return out
