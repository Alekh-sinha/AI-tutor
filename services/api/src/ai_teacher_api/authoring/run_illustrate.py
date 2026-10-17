"""Agent 1 as an ADK Workflow with a review loop:  draft (ReAct illustrator) -> critique -> fix (back to draft) | ok -> finish.

uv run python -m ai_teacher_api.run_illustrate ../../data/ch6 lesson-1 [--model gemini-3.6-flash] [--image-model gemini-3.1-flash-image]
Traces go to Langfuse when the keys are in services/api/.env.
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import START, Workflow, node
from google.genai import types

from ai_teacher_api.common import tracing
from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.content.brief import build_brief
from ai_teacher_api.authoring.review import critique_lecture, lecture_checks, lecture_gaps
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, REVIEW_MODEL, REVIEW_PASSES

MAX_ROUNDS = 2  # revisions allowed after feedback (so at most 3 drafts)
FIRST_BUDGET, REVISE_BUDGET = 30, 12


@dataclass
class Job:
    d: Path
    lesson_id: str
    model: str
    image_model: str
    chapter: dict
    plan: dict
    lesson: dict
    plan_text: str = ""


async def _run_agent(job: Job, message: str, stats: dict, model: str) -> str:
    sessions = InMemorySessionService()
    runner = Runner(agent=ill.build_illustrator(model), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    final = ""
    async for e in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        for c in e.get_function_calls():
            stats["tool_calls"] += 1
            a = dict(c.args or {})
            print(f"[draw] {a.get('name')} refs={a.get('references', '')!r}", flush=True)
        if e.usage_metadata:
            stats["llm_calls"] += 1
            stats["prompt_tokens"] += e.usage_metadata.prompt_token_count or 0
            stats["output_tokens"] += e.usage_metadata.candidates_token_count or 0
        if e.is_final_response() and e.content and e.content.parts:
            final = "".join(p.text or "" for p in e.content.parts)
    return final


def build_workflow(job: Job, stats: dict) -> Workflow:
    base = f"# LESSON PLAN\n{job.plan_text}"
    img_dir = job.d / "illustrated" / job.lesson_id

    @node(name="draft")
    async def draft(ctx, node_input):
        rnd = ctx.state.get("round", 0) + 1
        ctx.state["round"] = rnd
        issues = ctx.state.get("issues", [])
        msg = base
        if rnd > 1:
            ill.set_budget(REVISE_BUDGET)
            existing = sorted(p.stem for p in img_dir.glob("*.webp"))
            ill.set_redraw_allowed({n for n in existing if any(n in i for i in issues)})
            msg += (
                f"\n\nPREVIOUS LECTURE:\n{ctx.state['md']}\n\nREVIEWER FEEDBACK (fix every item; redraw only flagged photos):\n"
                + "\n".join(f"- {i}" for i in issues)
                + f"\n\nPhotographs that already exist (keep them unless flagged): {existing}"
            )
        else:
            ill.set_budget(FIRST_BUDGET)
            ill.set_redraw_allowed(None)
        print(f"=== draft round {rnd} ===", flush=True)
        t0 = time.time()
        md, used = await with_model_fallback(lambda m: _run_agent(job, msg, stats, m), job.model)
        stats["rounds"].append({"round": rnd, "seconds": round(time.time() - t0), "model": used, "image_calls": ill._state["calls"]})
        ctx.state["md"] = md
        return md

    @node(name="critique")
    async def critique(ctx, node_input):
        rnd = ctx.state["round"]
        md = ctx.state["md"]
        print(f"=== critique round {rnd} ===", flush=True)
        issues = lecture_checks(md, img_dir, len(job.lesson["beats"]))
        for k in range(REVIEW_PASSES):  # independent passes of a stronger model; every finding counts
            found, used = await with_model_fallback(
                lambda m: critique_lecture(md, job.plan_text, img_dir, m, img_dir / f"audit-round-{rnd}-pass-{k + 1}.json"), REVIEW_MODEL
            )
            print(f"  review pass {k + 1} ({used}): {len(found)} finding(s)", flush=True)
            issues += [f for f in found if f not in issues]
        (img_dir / f"review-round-{rnd}.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1))
        print(f"{len(issues)} issue(s) in round {rnd}", flush=True)
        for i in issues:
            print("  -", i[:230], flush=True)
        ctx.state["issues"] = issues
        stats["rounds"][-1]["issues"] = len(issues)
        route = "fix" if issues and rnd <= MAX_ROUNDS else "ok"
        return Event(output=md, route=route)

    @node(name="finish")
    async def finish(ctx, node_input):
        (img_dir / "lecture.md").write_text(ctx.state["md"])
        stats["remaining_issues"] = ctx.state.get("issues", [])
        stats["gaps_reported_by_agent"] = lecture_gaps(ctx.state["md"])
        return "done"

    return Workflow(name="illustrated_lesson", edges=[(START, draft), (draft, critique), (critique, {"fix": draft, "ok": finish})])


async def execute(job: Job) -> dict:
    img_dir = job.d / "illustrated" / job.lesson_id
    ill.configure(img_dir, job.image_model)
    stats = {"tool_calls": 0, "llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "rounds": []}
    t0 = time.time()
    sessions = InMemorySessionService()
    runner = Runner(node=build_workflow(job, stats), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text="run")])):
        pass
    attempts = ill._state["attempts"]
    stats.update(
        image_model=job.image_model, seconds=round(time.time() - t0), images_made=len(ill._state["log"]),
        image_attempts=len(attempts), image_attempts_failed=sum(a["outcome"] != "ok" for a in attempts),
        pictures_on_disk=len(list(img_dir.glob("*.webp"))), image_log=ill._state["log"],
    )
    (img_dir / "metrics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    return stats


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, image_model: str = ill.IMAGE_MODEL) -> dict:
    chapter, plan = json.loads((d / "chapter.json").read_text()), json.loads((d / "plan.json").read_text())
    lesson = next(l for l in plan["lessons"] if l["id"] == lesson_id)
    tracing.init()
    plan_text = asyncio.run(build_brief(d, chapter, lesson, model))
    print("=== PLAN given to Agent 1 ===\n" + plan_text + "\n=== end of plan ===", flush=True)
    stats = asyncio.run(execute(Job(d, lesson_id, model, image_model, chapter, plan, lesson, plan_text)))
    tracing.flush()
    print(json.dumps({k: v for k, v in stats.items() if k not in ("image_log", "remaining_issues")}, indent=1, ensure_ascii=False))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--image-model", default=ill.IMAGE_MODEL)
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.model, a.image_model)


if __name__ == "__main__":
    main()
