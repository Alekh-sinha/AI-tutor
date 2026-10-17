"""One lesson end to end with the two-agent approach:
brief (what the book says) -> Agent 1 draws and writes the illustrated lecture -> reviewers + editor loop -> Agent 2 (director) -> audio -> playable lesson.

uv run python -m ai_teacher_api.run_lesson ../../data/ch6 lesson-2 [--out-id lesson-2-v2] [--force]
Each stage is resumable: its output file is reused unless --force.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path

from ai_teacher_api.director import run_direct
from ai_teacher_api.common import tracing
from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.content.brief import build_brief
from ai_teacher_api.authoring.edit_loop import improve
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.run_illustrate import FIRST_BUDGET, Job, _run_agent
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, DEFAULT_VOICE


log = logsetup.get("content")

AUTHOR_Q = ("In at most 6 short bullets, for debugging: how many pictures you drew and how many you used; which moments have no picture and why; whether tool errors or limits "
            "changed what you did; anything in your instructions or plan that was unclear or conflicting.")
DIRECTOR_Q = ("In at most 6 short bullets, for debugging: how you decided where scenes start; what in the lecture or your instructions made the board rules hard (gaps, question cards, "
              "pictures); what content you condensed or dropped and why; anything unclear or conflicting in your instructions.")


def _interview(ask, who: str, lesson_id: str) -> None:
    """Every built lesson gets a short interview with each agent (answers go to logs/<feature>.jsonl as `explanation`); it must never break the build."""
    try:
        ask()
    except Exception as e:  # noqa: BLE001
        log.warn("interview-failed", agent=who, lesson=lesson_id, error=repr(e)[:200])


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, image_model: str = ill.IMAGE_MODEL, voice: str = DEFAULT_VOICE,
        out_id: str | None = None, force: bool = False, progress: Callable[[str], None] | None = None) -> dict:
    out_id = out_id or f"{lesson_id}-v2"
    note = progress or (lambda stage: None)
    t_start = time.time()
    chapter, plan = json.loads((d / "chapter.json").read_text()), json.loads((d / "plan.json").read_text())
    lesson = next(l for l in plan["lessons"] if l["id"] == lesson_id)
    concepts = len(lesson["beats"])
    img_dir = d / "illustrated" / f"{lesson_id}-final"
    tracing.init()
    note("brief: what the book says")
    plan_text = asyncio.run(build_brief(d, chapter, lesson, model))
    summary: dict = {"lesson": lesson_id, "out_id": out_id}

    draft_file = img_dir / "lecture.draft.md"
    if force or not draft_file.exists():
        print(f"=== {lesson_id}: Agent 1 draws and writes ===", flush=True)
        note("Agent 1: writing the lecture and drawing pictures (about 10 minutes)")
        ill.configure(img_dir, image_model)
        ill.set_budget(FIRST_BUDGET)
        stats = {"tool_calls": 0, "llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0}
        job = Job(d, lesson_id, model, image_model, chapter, plan, lesson, plan_text)
        md, used = asyncio.run(with_model_fallback(lambda m: _run_agent(job, f"# LESSON PLAN\n{plan_text}", stats, m), model))
        if not md.strip():
            raise RuntimeError("Agent 1 returned no lecture")
        draft_file.write_text(md)
        log.info("draft", lesson=lesson_id, words=len(md.split()), pictures=md.count("!["), image_attempts=len(ill._state["attempts"]), failed_attempts=sum(a["outcome"] != "ok" for a in ill._state["attempts"]), stats=stats)
        summary["draft"] = {**stats, "image_attempts": len(ill._state["attempts"])}

    _interview(lambda: __import__("ai_teacher_api.authoring.explain", fromlist=["x"]).explain_author(d, lesson_id, AUTHOR_Q, model), "author", lesson_id)

    done_file = img_dir / "improve.json"
    if force or not done_file.exists():
        print(f"=== {lesson_id}: reviewers + editor ===", flush=True)
        note("reviewers and editor: checking and fixing the lecture (about 10 minutes)")
        res = asyncio.run(improve(img_dir, plan_text, draft_file.read_text(), concepts, model))
        done_file.write_text(json.dumps({k: v for k, v in res.items() if k != "md"}, ensure_ascii=False, indent=1))
        summary["improve"] = {"seconds": res["seconds"], "left_for_teacher": len(res["for_teacher"])}
        log.info("improve", lesson=lesson_id, seconds=res["seconds"], findings_per_round=[r.get("findings") for r in res["rounds"]], left_for_teacher=res["for_teacher"])

    print(f"=== {lesson_id}: Agent 2 (director) + audio ===", flush=True)
    note("Agent 2: directing the video and recording the voice (about 8 minutes)")
    summary["direct"] = run_direct.run(d, lesson_id, model, voice, img_dir, out_id)
    _interview(lambda: __import__("ai_teacher_api.director.explain", fromlist=["x"]).explain_director(d, lesson_id, out_id, DIRECTOR_Q, model), "director", lesson_id)
    log.info("lesson-built", lesson=lesson_id, out_id=out_id, seconds=round(time.time() - t_start))
    (d / f"lesson-run-{lesson_id}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    tracing.flush()
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--image-model", default=ill.IMAGE_MODEL)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--out-id")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.model, a.image_model, a.voice, a.out_id, a.force)


if __name__ == "__main__":
    main()
