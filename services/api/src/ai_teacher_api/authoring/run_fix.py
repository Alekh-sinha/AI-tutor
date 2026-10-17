"""Fix-loop experiments. All variants start from the SAME frozen lecture and the SAME list of review findings, and are judged by the same reviewer.

  uv run python -m ai_teacher_api.run_fix baseline ../../data/ch6/illustrated/exp-baseline          # review the frozen lecture once
  uv run python -m ai_teacher_api.run_fix author|editor|harness ../../data/ch6/illustrated/exp-baseline ../../data/ch6/illustrated/exp-<variant>

author  = Exp 1: the Agent-1 author revises (same architecture), now with an edit_image tool
editor  = Exp 2: a separate short-context editor node (view_picture, edit_image, generate_image, replace_text)
harness = Exp 3: the editor plus a shell and file system (bubblewrap sandbox: only the work folder writable, no network)
"""

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from google.adk.agents import LlmAgent, RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.common import tracing
from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.content.brief import LessonBrief, render
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.review import critique_lecture, lecture_checks, lecture_images
from ai_teacher_api.common.sandbox import run_in_sandbox
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, REVIEW_MODEL, REVIEW_PASSES, resolve_model

MAX_FIX_ROUNDS = 3
IMAGE_BUDGET_PER_ROUND = 10
MAX_LLM_CALLS = 40
CONCEPTS = 3

# ---------------------------------------------------------------- review (identical for every variant)
def _key(issue: str) -> str:
    where = issue.removeprefix("[critic] ").removeprefix("[check] ").split(":", 1)[0].strip().lower()
    plain = where.replace("picture ", "")
    return plain if (" " not in plain and not plain.startswith(("concept", "opening", "recap", "home"))) else issue


def merge(issues: list[str]) -> list[str]:
    """One finding per picture id (keep the longest), every other finding as is."""
    best: dict[str, str] = {}
    for i in issues:
        k = _key(i)
        if k not in best or len(i) > len(best[k]):
            best[k] = i
    return list(best.values())


async def review(md: str, plan_text: str, d: Path, tag: str) -> list[str]:
    found = lecture_checks(md, d, CONCEPTS)
    for k in range(REVIEW_PASSES):
        got, _ = await with_model_fallback(lambda m: critique_lecture(md, plan_text, d, m, d / f"audit-{tag}-pass-{k + 1}.json"), REVIEW_MODEL)
        found += got
    return merge(found)


# ---------------------------------------------------------------- the fixers
_doc = {"md": ""}


def replace_text(old: str, new: str) -> dict:
    """Edit the lesson text: replace the passage `old` (it must appear EXACTLY ONCE in the lesson) with `new`. Use it for wording, questions, and to place a new picture reference."""
    n = _doc["md"].count(old)
    if n != 1:
        return {"status": "error", "error": f"`old` appears {n} times; it must appear exactly once. Include more surrounding text."}
    _doc["md"] = _doc["md"].replace(old, new)
    return {"status": "ok"}


def _sandbox_tool(workdir: Path):
    def sandbox_bash(command: str) -> dict:
        """Run a shell command in your workspace (python3 with Pillow is available, network access). Returns exit_code and output."""
        r = run_in_sandbox(command, workdir, network=True)
        with (workdir / "harness-commands.jsonl").open("a") as f:
            f.write(json.dumps({"at": time.strftime("%H:%M:%S"), "command": command, "exit_code": r["exit_code"], "output": r["output"][:1500]}, ensure_ascii=False) + "\n")
        return r

    return sandbox_bash


EDITOR_COMMON = """You are the editor of an illustrated lesson for Class 6 children in rural Bihar (Hindi). A reviewer has listed problems. Fix exactly those problems and
nothing else; do not rewrite or reorganise the lesson, and keep everything that was not flagged.
For a picture problem: look at the picture, change it, and look at the result. If one edit does not fix a picture, stop editing it: simplify the lesson so that it asks for
less (change the narration and the picture description so they say only what the picture clearly shows) instead of trying again. A text problem is fixed by editing the text.
For an attention gap (a long stretch of narration with nothing new on screen) add one new picture with a new name and place it where the point changes. Pictures are
photographs with no text; definitions and labels belong in the narration.
When every issue is handled, reply 'done' with one line per issue saying what you did."""

EDITOR_TOOLS = """
Tools: view_picture(name); edit_image(name, change) changes only what you ask, so keep it to one concrete change; generate_image(name, prompt) only for a NEW picture;
replace_text(old, new) edits the lesson (old must appear exactly once in the lesson text)."""

HARNESS_FREE = """You are an autonomous agent working on an illustrated lesson for Class 6 children in rural Bihar (Hindi). A reviewer has listed problems with it (issues.json).
Your goal: leave the lesson free of those problems. Every picture must show what the lesson says it shows, with no text or brand names in any picture; the lesson must stay correct,
in simple Hindi, and must not be rewritten beyond what is needed. Your workspace is the current directory: lecture.md, issues.json, and the pictures as NAME.webp. You have a shell
with full freedom inside this workspace (python3 with Pillow, network access): use whatever method you think works best. Also available: view_picture(name), edit_image(name, change)
and generate_image(name, prompt), which use the image model. When you are finished, reply 'done' and say what you did."""

HARNESS_TOOLS_OLD = """
Your workspace is the current directory: lecture.md (the lesson), issues.json, and the pictures as NAME.webp. You have a shell (python3 with Pillow; no network; only this
folder is writable): edit lecture.md in place with it, and use it for anything easier by code, such as cropping, blurring or painting over part of a picture.
Tools: sandbox_bash(command); view_picture(name); edit_image(name, change) asks the image model to change a picture; generate_image(name, prompt) for a NEW picture."""


def build_fixer(variant: str, model: str, workdir: Path, author_plan: str) -> LlmAgent:
    m = resolve_model(model)
    if variant == "author":
        return LlmAgent(name="illustrator", model=m, instruction=ill.INSTRUCTION, tools=[ill.generate_image, ill.edit_image])
    if variant == "editor":
        return LlmAgent(name="editor", model=m, instruction=EDITOR_COMMON + EDITOR_TOOLS,
                        tools=[ill.view_picture, ill.edit_image, ill.generate_image, replace_text])
    return LlmAgent(name="harness", model=m, instruction=HARNESS_FREE,
                    tools=[_sandbox_tool(workdir), ill.view_picture, ill.edit_image, ill.generate_image])


def fixer_message(variant: str, plan_text: str, md: str, issues: list[str], d: Path) -> str:
    used = {n for _, n in lecture_images(md)}
    names = sorted(p.stem for p in d.glob("*.webp") if p.stem in used)
    fb = "\n".join(f"- {i}" for i in issues)
    if variant == "author":
        return (f"# LESSON PLAN\n{plan_text}\n\nPREVIOUS LECTURE:\n{md}\n\nREVIEWER FEEDBACK (fix every item; change only what the feedback names, keep everything else):\n{fb}\n\n"
                f"Pictures that exist: {names}. To fix a flagged photograph use edit_image (it changes only what you ask); generate_image is for NEW pictures with new names. "
                "Return the full updated lecture.")
    if variant == "editor":
        return f"REVIEWER FINDINGS:\n{fb}\n\nPictures that exist: {names}\n\nTHE LESSON:\n{md}"
    return f"The reviewer's findings are in issues.json (also here):\n{fb}"


async def run_fixer(variant: str, model: str, d: Path, plan_text: str, md: str, issues: list[str], stats: dict) -> str:
    flagged = {n for n in (p.stem for p in d.glob("*.webp")) if any(n in i for i in issues)}
    ill.set_budget(IMAGE_BUDGET_PER_ROUND)
    ill.set_redraw_allowed(None if variant == "harness" else flagged)  # the harness gets no guard
    _doc["md"] = md
    if variant == "harness":
        (d / "lecture.md").write_text(md)
        (d / "issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1))
    agent = build_fixer(variant, model, d, plan_text)
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    final = ""
    msg = types.Content(role="user", parts=[types.Part(text=fixer_message(variant, plan_text, md, issues, d))])
    async for e in runner.run_async(user_id="teacher", session_id=session.id, new_message=msg, run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
        for c in e.get_function_calls():
            stats["tools"][c.name] = stats["tools"].get(c.name, 0) + 1
            a = dict(c.args or {})
            print(f"[{variant}] {c.name} {str(a.get('name') or a.get('command') or '')[:80]}", flush=True)
        if e.usage_metadata:
            stats["llm_calls"] += 1
            stats["prompt_tokens"] += e.usage_metadata.prompt_token_count or 0
            stats["output_tokens"] += e.usage_metadata.candidates_token_count or 0
        if e.is_final_response() and e.content and e.content.parts:
            final = "".join(p.text or "" for p in e.content.parts)
    if variant == "author":
        return final
    if variant == "harness":
        return (d / "lecture.md").read_text()
    return _doc["md"]


# ---------------------------------------------------------------- the experiment
def plan_text_for(base: Path) -> str:
    return render(LessonBrief.model_validate_json((base.parent.parent / "brief-lesson-1.json").read_text()))


async def baseline(base: Path) -> None:
    md = (base / "lecture.md").read_text()
    issues = await review(md, plan_text_for(base), base, "baseline")
    (base / "baseline-issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1))
    print(f"baseline: {len(issues)} issue(s)")
    for i in issues:
        print("  -", i[:200])


async def experiment(variant: str, base: Path, out: Path, model: str) -> None:
    if out.exists():
        sys.exit(f"{out} already exists: pick a new folder (nothing is deleted by this script)")
    shutil.copytree(base, out)
    ill.configure(out, ill.IMAGE_MODEL)
    plan_text = plan_text_for(base)
    md = (out / "lecture.md").read_text()
    issues = json.loads((base / "baseline-issues.json").read_text())
    t_all = time.time()
    rounds = [{"review": 0, "issues": len(issues), "list": issues}]
    for rnd in range(1, MAX_FIX_ROUNDS + 1):
        stats = {"llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "tools": {}}
        n_attempts_before = len(ill._state["attempts"])
        t0 = time.time()
        new_md, used = await with_model_fallback(lambda m: run_fixer(variant, m, out, plan_text, md, issues, stats), model)
        md = new_md or md
        (out / "lecture.md").write_text(md)
        fix_s = round(time.time() - t0)
        attempts = ill._state["attempts"][n_attempts_before:]
        t1 = time.time()
        issues = await review(md, plan_text, out, f"round{rnd}")
        rounds.append({"fix_round": rnd, "fix_seconds": fix_s, "review_seconds": round(time.time() - t1), "fixer": stats,
                       "image_attempts": len(attempts), "image_attempts_rejected": sum(a["outcome"] != "ok" for a in attempts),
                       "issues": len(issues), "list": issues})
        print(f"=== fix round {rnd}: {fix_s}s, tools {stats['tools']}, review -> {len(issues)} issue(s)", flush=True)
        for i in issues:
            print("  -", i[:200], flush=True)
        if not issues:
            break
    result = {"variant": variant, "total_seconds": round(time.time() - t_all), "rounds": rounds, "unresolved": issues,
              "pictures_referenced": len(lecture_images(md)), "pictures_on_disk": len(list(out.glob("*.webp")))}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k not in ("rounds", "unresolved")}, indent=1))


async def improved(base: Path, out: Path, model: str) -> None:
    """The production loop (edit_loop.improve) on the same frozen lecture: new reviewer (640 px per picture, agreement) + editor with frozen pictures."""
    from ai_teacher_api.authoring.edit_loop import improve

    if out.exists():
        sys.exit(f"{out} already exists: pick a new folder")
    shutil.copytree(base, out)
    ill.configure(out, ill.IMAGE_MODEL)
    res = await improve(out, plan_text_for(base), (out / "lecture.md").read_text(), CONCEPTS, model)
    (out / "result.json").write_text(json.dumps({k: v for k, v in res.items() if k != "md"}, ensure_ascii=False, indent=1))
    print("left for the teacher:", json.dumps(res["for_teacher"], ensure_ascii=False, indent=1), "seconds", res["seconds"])


def main() -> None:
    tracing.init()
    if sys.argv[1] == "improve":
        asyncio.run(improved(Path(sys.argv[2]), Path(sys.argv[3]), DEFAULT_TEXT_MODEL))
        tracing.flush()
        return
    if sys.argv[1] == "baseline":
        asyncio.run(baseline(Path(sys.argv[2])))
    else:
        asyncio.run(experiment(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), DEFAULT_TEXT_MODEL))
    tracing.flush()


if __name__ == "__main__":
    main()
