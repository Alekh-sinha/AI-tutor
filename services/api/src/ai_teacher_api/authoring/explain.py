"""Interview Agent 1 (the illustrator) about a lecture it wrote (logs to logs/authoring.jsonl).

    uv run python -m ai_teacher_api.authoring.explain ../../data/ch6 lesson-4 "why only 7 pictures?"
"""

import asyncio
import sys
from pathlib import Path

from ai_teacher_api.authoring.illustrator import INSTRUCTION
from ai_teacher_api.authoring.review import lecture_images
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.explain import ask
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL


def explain_author(d: Path, lesson_id: str, question: str, model: str = DEFAULT_TEXT_MODEL) -> str:
    folder = d / "illustrated" / f"{lesson_id}-final"
    draft = (folder / "lecture.draft.md").read_text()
    attempts = (folder / "image-attempts.jsonl").read_text() if (folder / "image-attempts.jsonl").exists() else ""
    material = f"(the lesson plan was given to you as in your instruction; the image tool log of your run follows)\n{attempts[-3000:]}"
    output = f"{draft}\n\nPictures in your draft: {len(lecture_images(draft))}"
    answer, _ = asyncio.run(with_model_fallback(lambda m: ask(INSTRUCTION, material, output, question, m), model))
    logsetup.get("authoring").info("explanation", lesson=lesson_id, question=question, answer=answer)
    return answer


if __name__ == "__main__":
    print(explain_author(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
