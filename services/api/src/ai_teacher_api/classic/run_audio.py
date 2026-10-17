"""Steps 4+6: script-<id>.json -> audio mp3 + timings + playable lesson JSON in apps/web/public.

uv run python -m ai_teacher_api.run_audio ../../data/ch6 lesson-1 [--voice Kore]
"""

import argparse
import asyncio
import json
from pathlib import Path

from ai_teacher_api.director.assemble import assemble
from ai_teacher_api.director.script import LessonScript
from ai_teacher_api.common.settings import DEFAULT_VOICE, WEB_PUBLIC
from ai_teacher_api.common.tts import narrate



def run(d: Path, lesson_id: str, voice: str = DEFAULT_VOICE, assemble_only: bool = False) -> None:
    script = LessonScript.model_validate_json((d / f"script-{lesson_id}.json").read_text())
    if assemble_only:
        mp3 = (d / "audio" / f"{lesson_id}.mp3").read_bytes()
        timings = json.loads((d / f"timings-{lesson_id}.json").read_text())
    else:
        mp3, timings = asyncio.run(narrate(script, voice=voice))
        (d / "audio").mkdir(exist_ok=True)
        (d / "audio" / f"{lesson_id}.mp3").write_bytes(mp3)
        (d / f"timings-{lesson_id}.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1))
    svg_file = d / f"visuals-{lesson_id}.json"
    svgs = json.loads(svg_file.read_text()) if svg_file.exists() else {}
    plan = json.loads((d / "chapter.json").read_text())
    outline = next(l for l in json.loads((d / "plan.json").read_text())["lessons"] if l["id"] == lesson_id)
    audio_dir = WEB_PUBLIC / "audio"
    audio_dir.mkdir(exist_ok=True)
    (audio_dir / f"{lesson_id}.mp3").write_bytes(mp3)
    img_out = WEB_PUBLIC / "img"
    img_out.mkdir(exist_ok=True)
    image_srcs = {}
    for f in (d / "images").glob(f"{lesson_id}-*.webp") if (d / "images").exists() else []:
        (img_out / f.name).write_bytes(f.read_bytes())
        image_srcs[f.stem[len(lesson_id) + 1 :]] = f"/img/{f.name}"
    lesson = assemble(script, timings, f"/audio/{lesson_id}.mp3", plan["book"], svgs, image_srcs, outline["quiz"], outline["home_activity"])
    (WEB_PUBLIC / "lessons" / f"{lesson_id}.json").write_text(
        json.dumps(lesson.model_dump(), ensure_ascii=False, indent=1)
    )
    print(f"audio {len(mp3) / 1024:.0f} KB, duration {lesson.duration:.0f}s, {len(lesson.events)} events -> {WEB_PUBLIC}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--assemble-only", action="store_true", help="reuse existing audio + timings (no TTS cost)")
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.voice, a.assemble_only)


if __name__ == "__main__":
    main()
