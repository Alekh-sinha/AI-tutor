"""Chapter pipeline as an ADK Workflow: PDF -> parse -> plan -> (per lesson) script -> visuals -> audio+assemble.

uv run python -m ai_teacher_api.pipeline ../../docs/source/fecu106.pdf ../../data/ch6 --book "NCERT Class 6 Science, Ch. 6"

Each stage is resumable: it is skipped when its output already exists (use --force to redo everything, or delete the
stage's file). Lessons run one after another on purpose (parallel runs hit model quota). The output is a DRAFT: a
teacher must review it before it is published (editor: Phase 3).
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import START, Workflow, node
from google.genai import types

from ai_teacher_api.content import chapter
from ai_teacher_api.classic import run_audio
from ai_teacher_api.content import run_lesson
from ai_teacher_api.content import run_plan
from ai_teacher_api.classic import run_review
from ai_teacher_api.classic import run_script
from ai_teacher_api.classic import run_visuals
from ai_teacher_api.director.script import LessonScript, rhythm_problems
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, DEFAULT_VOICE, WEB_PUBLIC


@dataclass
class Config:
    pdf: Path
    out: Path
    book: str
    model: str = DEFAULT_TEXT_MODEL
    voice: str = DEFAULT_VOICE
    language: str = "hi-IN"
    region: str = "Bihar"
    grade: int = 6
    lessons: list[str] | None = None  # None = every lesson in the plan
    force: bool = False
    approach: str = "agents"  # "agents" = Agent 1 + review/edit loop + Agent 2 (director); "classic" = planner -> scripter -> visualizer


def _script_ok(path: Path, concepts: int) -> bool:
    return path.exists() and not rhythm_problems(LessonScript.model_validate_json(path.read_text()), concepts)


def _fresh(out: Path, *inputs: Path) -> bool:
    """A stage's output is up to date if it exists and is newer than everything it was made from."""
    return out.exists() and all(not i.exists() or out.stat().st_mtime >= i.stat().st_mtime for i in inputs)


def build_pipeline(cfg: Config) -> Workflow:
    d = cfg.out
    d.mkdir(parents=True, exist_ok=True)

    @node(name="parse")
    async def parse(ctx, node_input):
        out = d / "chapter.json"
        if cfg.force or not out.exists():
            ch = await asyncio.to_thread(chapter.parse_chapter, cfg.pdf, cfg.book)
            out.write_text(json.dumps(ch.model_dump(), ensure_ascii=False, indent=2) + "\n")
        return str(out)

    @node(name="plan")
    async def plan(ctx, node_input):
        out = d / "plan.json"
        if cfg.force or not out.exists():
            await asyncio.to_thread(run_plan.run, d / "chapter.json", out, cfg.model, cfg.language, cfg.region, cfg.grade)
        ids = [l["id"] for l in json.loads(out.read_text())["lessons"]]
        ctx.state["lesson_ids"] = [i for i in ids if cfg.lessons is None or i in cfg.lessons]
        return ctx.state["lesson_ids"]

    @node(name="lessons")
    async def lessons(ctx, node_input):
        done = []
        for lid in ctx.state["lesson_ids"]:
            if cfg.approach == "agents":
                await asyncio.to_thread(run_lesson.run, d, lid, cfg.model, voice=cfg.voice, force=cfg.force)
                done.append(f"{lid}-v2")
                continue
            print(f"=== {lid}: script ===", flush=True)
            concepts = len(next(l for l in json.loads((d / "plan.json").read_text())["lessons"] if l["id"] == lid)["beats"])
            if cfg.force or not _script_ok(d / f"script-{lid}.json", concepts):
                await asyncio.to_thread(run_script.run, d, lid, cfg.model, (d / f"script-{lid}.json").exists() and not cfg.force)
            print(f"=== {lid}: visuals ===", flush=True)
            if cfg.force or not _fresh(d / f"visuals-{lid}.json", d / f"script-{lid}.json"):
                await asyncio.to_thread(run_visuals.run, d, lid, cfg.model)
            print(f"=== {lid}: audio + assemble ===", flush=True)
            script_file, final = d / f"script-{lid}.json", WEB_PUBLIC / "lessons" / f"{lid}.json"
            if cfg.force or not _fresh(final, script_file, d / f"visuals-{lid}.json", d / "plan.json"):
                # new audio only when the words changed; otherwise just re-assemble from the saved timings
                reuse = _fresh(d / f"timings-{lid}.json", script_file) and not cfg.force
                await asyncio.to_thread(run_audio.run, d, lid, cfg.voice, reuse)
            print(f"=== {lid}: picture review ===", flush=True)
            redo = await asyncio.to_thread(run_review.run, d, lid, cfg.model)
            if redo:  # one repair round: redraw only the rejected photos, then look again
                await asyncio.to_thread(run_visuals.run, d, lid, cfg.model, redo)
                await asyncio.to_thread(run_audio.run, d, lid, cfg.voice, True)
                await asyncio.to_thread(run_review.run, d, lid, cfg.model, "-after")
            done.append(lid)
        return done

    @node(name="report")
    async def report(ctx, node_input):
        # index for the player's lesson list: every built lesson file (classic ids and "-v2" ids of the agent approach); keep a lesson's earlier status (draft / published)
        idx_file = WEB_PUBLIC / "lessons" / "index.json"
        old = {e["id"]: e for e in (json.loads(idx_file.read_text()) if idx_file.exists() else [])}
        index = []
        for f in sorted((WEB_PUBLIC / "lessons").glob("lesson-*.json")):
            built = json.loads(f.read_text())
            title = built["title"] + (" · v2" if f.stem.endswith("-v2") and not built["title"].endswith("v2") else "")
            index.append({"id": f.stem, "title": old.get(f.stem, {}).get("title", title), "duration": built["duration"], "status": old.get(f.stem, {}).get("status", "draft")})
        idx_file.write_text(json.dumps(index, ensure_ascii=False, indent=1))
        for lid in node_input:
            lesson = json.loads((WEB_PUBLIC / "lessons" / f"{lid}.json").read_text())
            kinds: dict[str, int] = {}
            for e in lesson["events"]:
                kinds[e["type"]] = kinds.get(e["type"], 0) + 1
            print(f"{lid}: {lesson['duration']:.0f}s DRAFT (needs teacher review) events={kinds} quiz={len(lesson['quiz'])}")
        return node_input

    return Workflow(name="chapter_pipeline", edges=[(START, parse), (parse, plan), (plan, lessons), (lessons, report)])


async def run_pipeline(cfg: Config) -> None:
    sessions = InMemorySessionService()
    runner = Runner(node=build_pipeline(cfg), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    msg = types.Content(role="user", parts=[types.Part(text="run")])
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=msg):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--book", required=True)
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--language", default="hi-IN")
    ap.add_argument("--region", default="Bihar")
    ap.add_argument("--grade", type=int, default=6)
    ap.add_argument("--lessons", nargs="*", help="only these lesson ids (default: all)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--approach", choices=["agents", "classic"], default="agents")
    a = ap.parse_args()
    asyncio.run(run_pipeline(Config(Path(a.pdf), Path(a.out), a.book, a.model, a.voice, a.language, a.region, a.grade, a.lessons, a.force, a.approach)))


if __name__ == "__main__":
    main()
