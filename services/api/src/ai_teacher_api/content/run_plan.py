"""Step 2: chapter.json -> plan.json using the ADK planner agent.

uv run python -m ai_teacher_api.run_plan ../../data/ch6/chapter.json ../../data/ch6/plan.json \
    --model gemini-3.6-flash --language hi-IN --region Bihar
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.content.planner import build_planner
from ai_teacher_api.content.plan import LessonPlan
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL


MAX_PROMPT_CHARS = 1_200_000  # about 400k tokens of the model's 1M window: room for the instructions, the skill files and the plan it writes
TOO_LONG = re.compile(r"exceeds? the maximum|input token count|too long|context (length|window)|maximum (number of )?tokens", re.I)


def pages_that_fit(chapter: dict, max_chars: int = MAX_PROMPT_CHARS) -> int:
    """How many pages from the start fit the budget (a whole book instead of a chapter is cut to its first pages, not rejected)."""
    used = 0
    for n, p in enumerate(chapter["pages"], 1):
        used += len(p["text"]) + 20
        if used > max_chars:
            return max(1, n - 1)
    return len(chapter["pages"])


def chapter_prompt(chapter: dict, language: str, region: str, grade: int, pages_limit: int | None = None) -> str:
    pages = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in chapter["pages"][:pages_limit])
    return (
        f"Settings: language={language}, region={region}, grade={grade}, max lesson minutes=10.\n"
        f"Book: {chapter['book']}. Chapter: {chapter['title']}.\n"
        f"Textbook activities: {[(a['id'], a['page'], a['title']) for a in chapter['activities']]}\n\n{pages}"
    )


async def plan_chapter(chapter: dict, *, model: str | None, language: str, region: str, grade: int, pages_limit: int | None = None) -> LessonPlan:
    agent = build_planner(model)
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    msg = types.Content(role="user", parts=[types.Part(text=chapter_prompt(chapter, language, region, grade, pages_limit))])
    async for event in runner.run_async(user_id="teacher", session_id=session.id, new_message=msg):
        for call in event.get_function_calls():
            print(f"[tool] {call.name} {dict(call.args or {})}", flush=True)
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return LessonPlan.model_validate(session.state["lesson_plan"])


def run(chapter_path: Path, out: Path, model: str = DEFAULT_TEXT_MODEL, language: str = "hi-IN", region: str = "Bihar", grade: int = 6) -> dict:
    """Plan the lessons. A PDF that is too long for the model (a whole book) is not an error: only its first pages are used (halved again if the model still says it is too long).
    Returns {"pages_used", "pages_total"} so the teacher can be told."""
    chapter = json.loads(chapter_path.read_text())
    total = len(chapter["pages"])
    limit = pages_that_fit(chapter)
    while True:
        try:
            plan, used = asyncio.run(
                with_model_fallback(lambda m: plan_chapter(chapter, model=m, language=language, region=region, grade=grade, pages_limit=limit), model)
            )
            break
        except Exception as e:  # noqa: BLE001
            if limit <= 1 or not TOO_LONG.search(str(e)):
                raise
            limit = max(1, limit // 2)
            print(f"[plan] the model says the input is too long: retrying with the first {limit} pages", flush=True)
    print(f"model used: {used}")
    data = plan.model_dump()
    for n, l in enumerate(data["lessons"], 1):  # the planner's ids vary (lesson_1, L1 ...): the rest of the system relies on lesson-<n>
        l["id"] = f"lesson-{n}"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    for l in plan.lessons:
        print(f"{l.id}: {l.title} ({sum(b.minutes for b in l.beats):.1f} min, pages {l.source_pages})")
    if limit < total:
        print(f"[plan] only the first {limit} of {total} pages were used", flush=True)
    return {"pages_used": limit, "pages_total": total}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("out")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--language", default="hi-IN")
    ap.add_argument("--region", default="Bihar")
    ap.add_argument("--grade", type=int, default=6)
    a = ap.parse_args()
    run(Path(a.chapter), Path(a.out), a.model, a.language, a.region, a.grade)


if __name__ == "__main__":
    main()
