"""Picture review node: contact sheets of the assembled lesson -> multimodal reviewer -> issues per photo.

The sheets are also the teacher's storyboard (data/<chapter>/storyboard/<lesson>-N.png).
"""

import asyncio
import json
from pathlib import Path

from ai_teacher_api.common.lesson import Lesson
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.review import contact_sheets, review_pictures
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, WEB_PUBLIC


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, tag: str = "") -> dict[str, str]:
    """Returns {image cue id: what is wrong + what it should show}; also saves the storyboard and the review."""
    lesson = Lesson.model_validate_json((WEB_PUBLIC / "lessons" / f"{lesson_id}.json").read_text())
    (d / "storyboard").mkdir(exist_ok=True)
    for i, png in enumerate(contact_sheets(lesson, WEB_PUBLIC)):
        (d / "storyboard" / f"{lesson_id}{tag}-{i + 1}.png").write_bytes(png)
    issues, used = asyncio.run(with_model_fallback(lambda m: review_pictures(lesson, WEB_PUBLIC, m), model))
    image_ids = {e.id for e in lesson.events if e.type == "image"}
    found = {i.where: f"{i.problem}. Should show: {i.fix}" for i in issues if i.where in image_ids}
    (d / f"review-{lesson_id}{tag}.json").write_text(json.dumps(found, ensure_ascii=False, indent=1))
    print(f"picture review ({used}): {len(found)} issue(s) {list(found)}")
    return found
