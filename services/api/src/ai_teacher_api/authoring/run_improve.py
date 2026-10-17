"""Run the review + edit loop again on an existing lecture (after the checks changed, or to fold in unused pictures). The old lecture is kept as lecture.before-<n>.md.

uv run python -m ai_teacher_api.authoring.run_improve ../../data/ch6 lesson-4
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.authoring.edit_loop import improve
from ai_teacher_api.common import logsetup, tracing
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL
from ai_teacher_api.content.brief import LessonBrief, render

log = logsetup.get("authoring")


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL) -> dict:
    folder = d / "illustrated" / f"{lesson_id}-final"
    plan = json.loads((d / "plan.json").read_text())
    concepts = len(next(l for l in plan["lessons"] if l["id"] == lesson_id)["beats"])
    plan_text = render(LessonBrief.model_validate_json((d / f"brief-{lesson_id}.json").read_text()))
    n = 1
    while (folder / f"lecture.before-{n}.md").exists():
        n += 1
    shutil.copy(folder / "lecture.md", folder / f"lecture.before-{n}.md")
    tracing.init()
    ill.configure(folder, ill.IMAGE_MODEL)
    res = asyncio.run(improve(folder, plan_text, (folder / "lecture.md").read_text(), concepts, model))
    (folder / f"improve-{n + 1}.json").write_text(json.dumps({k: v for k, v in res.items() if k != "md"}, ensure_ascii=False, indent=1))
    log.info("re-improve", lesson=lesson_id, seconds=res["seconds"], findings_per_round=[r.get("findings") for r in res["rounds"]], left_for_teacher=res["for_teacher"])
    tracing.flush()
    return res


if __name__ == "__main__":
    r = run(Path(sys.argv[1]), sys.argv[2])
    print("left for the teacher:", json.dumps(r["for_teacher"], ensure_ascii=False, indent=1))
