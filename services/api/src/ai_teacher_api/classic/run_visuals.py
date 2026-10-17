"""Step 5: script-<id>.json -> visuals-<id>.json (cue id -> SVG), plus PNG previews for review.

uv run python -m ai_teacher_api.run_visuals ../../data/ch6 lesson-1 --model gemini-3.6-flash
"""

import argparse
import asyncio
import json
from pathlib import Path

import resvg_py
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.classic.visualizer import build_visualizer
from ai_teacher_api.director.script import LessonScript
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.classic.illustrate import image_path, set_image_target
from ai_teacher_api.classic.visuals import LessonVisuals, check_svg, preview_svg, to_player_labels


FONT = Path(__file__).resolve().parents[3] / "assets/fonts/NotoSansDevanagari-Regular.ttf"


def visual_prompt(script: LessonScript, only: dict[str, list[str]] | None = None) -> str:
    cues = [(c.id, c.kind, c.description) for l in script.lines for c in l.cues if c.kind in ("svg", "image") and (only is None or c.id in only)]
    text = f"Language: {script.language}. Lesson: {script.title}.\nPicture cues:\n" + "\n".join(f"- {i} (kind={k}): {d}" for i, k, d in cues)
    if only:
        text += "\n\nYour previous drawings for these cues were rejected. Redraw them and fix:\n"
        text += "\n".join(f"- {i}: {'; '.join(p)}" for i, p in only.items())
    return text


async def draw(script: LessonScript, model: str | None, only: dict[str, list[str]] | None = None) -> LessonVisuals:
    sessions = InMemorySessionService()
    runner = Runner(agent=build_visualizer(model), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    msg = types.Content(role="user", parts=[types.Part(text=visual_prompt(script, only))])
    async for event in runner.run_async(user_id="teacher", session_id=session.id, new_message=msg):
        for call in event.get_function_calls():
            print(f"[tool] {call.name}", flush=True)
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return LessonVisuals.model_validate(session.state["lesson_visuals"])


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, redo: dict[str, str] | None = None) -> None:
    script = LessonScript.model_validate_json((d / f"script-{lesson_id}.json").read_text())
    (d / "preview").mkdir(exist_ok=True)
    wanted = [c.id for l in script.lines for c in l.cues if c.kind == "svg"]
    wanted_images = [c.id for l in script.lines for c in l.cues if c.kind == "image"]
    img_dir = d / "images"
    set_image_target(img_dir, lesson_id)
    out: dict[str, dict] = {}
    todo: dict[str, list[str]] | None = None
    if redo:  # picture review rejected these: keep everything else, redraw only these
        vf = d / f"visuals-{lesson_id}.json"
        out = json.loads(vf.read_text()) if vf.exists() else {}
        todo = {cid: [f"rejected by the reviewer: {why}"] for cid, why in redo.items()}
        for cid in redo:
            image_path(lesson_id, cid, img_dir).unlink(missing_ok=True)
            image_path(lesson_id, cid, img_dir).with_suffix(".scene").unlink(missing_ok=True)
    for round_ in range(1, 4):  # the agent's own "validated" claim is re-checked here; failures get redrawn
        vis, used = asyncio.run(with_model_fallback(lambda m: draw(script, m, todo), model))
        print(f"model used: {used}")
        failed: dict[str, list[str]] = {}
        for asset in vis.assets:
            if asset.cue_id not in wanted or asset.cue_id in out:
                continue
            problems = check_svg(asset.svg, asset.labels)
            print(f"round {round_} {asset.cue_id}: {len(asset.svg)} bytes, problems={problems}")
            if problems:
                failed[asset.cue_id] = problems
                continue
            out[asset.cue_id] = {"svg": asset.svg, "labels": to_player_labels(asset.svg, asset.labels)}
            (d / "preview" / f"{lesson_id}-{asset.cue_id}.png").write_bytes(
                bytes(resvg_py.svg_to_bytes(svg_string=preview_svg(asset.svg, asset.labels), background="white", width=960, font_files=[str(FONT)]))
            )
        for cid in wanted:
            if cid not in out and cid not in failed:
                failed[cid] = ["no drawing returned"]
        for cid in wanted_images:  # trust the file on disk, not the agent's claim
            if not image_path(lesson_id, cid, img_dir).exists():
                failed[cid] = ["no illustration file was produced: call generate_illustration with a simpler concrete scene"]
        print(f"round {round_}: images present {sum(image_path(lesson_id, c, img_dir).exists() for c in wanted_images)}/{len(wanted_images)}")
        if not failed:
            break
        todo = failed
    (d / f"visuals-{lesson_id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(out)}/{len(wanted)} diagrams ok, {sum(image_path(lesson_id, c, img_dir).exists() for c in wanted_images)}/{len(wanted_images)} images ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.model)


if __name__ == "__main__":
    main()
