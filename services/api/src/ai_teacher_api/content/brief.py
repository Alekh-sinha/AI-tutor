"""The lesson BRIEF = the teacher's memory notes for one video: what it is about, and per concept what the book says.

One cheap call per lesson (later the planner writes this itself). Agent 1 sees ONLY this, never the raw textbook pages.
"""

import json
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.settings import resolve_model


class ConceptBrief(BaseModel):
    idea: str = Field(description="The one idea of this concept, one sentence")
    book_says: list[str] = Field(min_length=2, max_length=6, description="Short points: key ideas, definitions, distinctions, and the book's terms")
    objective: str = Field(description="What the child can do afterwards, starting with 'The child can'")
    pages: list[int]


class LessonBrief(BaseModel):
    title: str
    about: str = Field(description="2-3 sentences: what this video is about and how it flows")
    concepts: list[ConceptBrief]


INSTRUCTION = """You write the teacher's memory notes for ONE lesson (one recorded video) of a Class 6 textbook. You get the textbook pages and the
lesson outline (title, objectives, the concepts in order). Keep exactly those concepts in that order.
For each concept write: its idea (one sentence); 3-5 short points saying what the BOOK says, i.e. the key ideas, definitions, distinctions and the book's
own terms as the book words them (when you are sure of the standard NCERT Hindi term, put it in brackets after the English term); the objective
('The child can ...', observable); the pages. Facts only: do NOT copy the book's characters, activities or examples, and add nothing the book does not say.
Also write `about`: 2-3 sentences on what the video is about and the order in which it unfolds. Be concise and plain."""


def render(b: LessonBrief) -> str:
    out = [f"Video: {b.title}", f"What this video is about: {b.about}", ""]
    for i, c in enumerate(b.concepts, 1):
        out += [f"Concept {i}: {c.idea}", "What the book says:"] + [f"- {p}" for p in c.book_says]
        out += [f"After this the child can: {c.objective.removeprefix('The child can ').removeprefix('the child can ')}", ""]
    return "\n".join(out).strip()


async def _summarize(pages: str, outline: dict, model: str) -> LessonBrief:
    agent = LlmAgent(name="brief_writer", model=resolve_model(model), instruction=INSTRUCTION, output_schema=LessonBrief, output_key="brief")
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    msg = f"LESSON OUTLINE:\n{json.dumps(outline, ensure_ascii=False, indent=1)}\n\nTEXTBOOK PAGES:\n{pages}"
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
        pass
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return LessonBrief.model_validate(session.state["brief"])


async def build_brief(d: Path, chapter: dict, lesson: dict, model: str, force: bool = False) -> str:
    """Return the Plan text for a lesson; cached in brief-<id>.json so a teacher can edit it before Agent 1 runs."""
    f = d / f"brief-{lesson['id']}.json"
    if f.exists() and not force:
        return render(LessonBrief.model_validate_json(f.read_text()))
    pages = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in chapter["pages"] if p["page"] in lesson["source_pages"])
    outline = {"title": lesson["title"], "objectives": lesson["objectives"], "concepts_in_order": [b["idea"] for b in lesson["beats"]]}
    brief, used = await with_model_fallback(lambda m: _summarize(pages, outline, m), model)
    f.write_text(brief.model_dump_json(indent=1, ensure_ascii=False))
    (d / f"brief-{lesson['id']}.md").write_text(render(brief))
    print(f"[brief] written with {used}", flush=True)
    return render(brief)
