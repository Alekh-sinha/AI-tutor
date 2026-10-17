"""Step 3: plan.json + chapter.json -> script-<lesson>.json (one lesson at a time).

uv run python -m ai_teacher_api.run_script ../../data/ch6 lesson-1 --model gemini-3.6-flash
"""

import argparse
import asyncio
import json
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.classic.scripter import build_scripter
from ai_teacher_api.director.script import LessonScript, rhythm_problems
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.review import review_script
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL


def lesson_prompt(chapter: dict, plan: dict, lesson: dict, previous: LessonScript | None = None, problems: list[str] | None = None) -> str:
    pages = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in chapter["pages"] if p["page"] in lesson["source_pages"])
    text = (
        f"Language: {plan['language']}. Region: {plan['region']}.\n\nLESSON OUTLINE:\n"
        f"{json.dumps(lesson, ensure_ascii=False, indent=1)}\n\nTEXTBOOK PAGES:\n{pages}"
    )
    if previous and problems:
        text += (
            "\n\nYOUR PREVIOUS SCRIPT WAS REJECTED by the automatic checks. Rewrite the WHOLE script, keeping its good "
            "wording, and fix every problem:\n" + "\n".join(f"- {p}" for p in problems)
            + "\n\nPREVIOUS SCRIPT:\n" + json.dumps(previous.model_dump(), ensure_ascii=False)
        )
    return text


async def script_lesson(chapter: dict, plan: dict, lesson: dict, *, model: str | None, previous: LessonScript | None = None, problems: list[str] | None = None) -> LessonScript:
    sessions = InMemorySessionService()
    runner = Runner(agent=build_scripter(model), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    msg = types.Content(role="user", parts=[types.Part(text=lesson_prompt(chapter, plan, lesson, previous, problems))])
    async for event in runner.run_async(user_id="teacher", session_id=session.id, new_message=msg):
        for call in event.get_function_calls():
            print(f"[tool] {call.name} {dict(call.args or {})}", flush=True)
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return LessonScript.model_validate(session.state["lesson_script"])


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, revise: bool = False) -> None:
    chapter, plan = json.loads((d / "chapter.json").read_text()), json.loads((d / "plan.json").read_text())
    lesson = next(l for l in plan["lessons"] if l["id"] == lesson_id)
    script, problems = None, []
    existing = d / f"script-{lesson_id}.json"
    if revise and existing.exists():
        script = LessonScript.model_validate_json(existing.read_text())
        problems = rhythm_problems(script, len(lesson['beats']))
        problems += asyncio.run(with_model_fallback(lambda m: review_script(script, m), model))[0]
        print(f"revising existing script: {len(problems)} problem(s) to fix first")
    for round_ in range(1, 4):  # the rhythm rules are checked in code; failures go back to the writer
        script, used = asyncio.run(
            with_model_fallback(lambda m: script_lesson(chapter, plan, lesson, model=m, previous=script, problems=problems), model)
        )
        problems = rhythm_problems(script, len(lesson['beats']))
        reviewed, _ = asyncio.run(with_model_fallback(lambda m: review_script(script, m), model))  # does the board match the voice?
        problems += reviewed
        print(f"round {round_} model {used}: {len(problems)} problem(s) ({len(reviewed)} from the reviewer)")
        for p in problems:
            print("  -", p)
        if not problems:
            break
    out = d / f"script-{lesson_id}.json"
    out.write_text(json.dumps(script.model_dump(), ensure_ascii=False, indent=2) + "\n")
    words = sum(len(l.text.split()) for l in script.lines)
    print(f"{out}: {len(script.lines)} lines, {words} words (~{words / 130:.1f} min), cues {sum(len(l.cues) for l in script.lines)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--revise", action="store_true", help="start from the existing script and fix what the checks find")
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.model, a.revise)


if __name__ == "__main__":
    main()
