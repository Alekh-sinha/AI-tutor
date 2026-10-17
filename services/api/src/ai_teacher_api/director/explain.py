"""Interview the director about a built lesson (logs to logs/director.jsonl).

    uv run python -m ai_teacher_api.director.explain ../../data/ch6 lesson-3 "why so few scene changes?"
"""

import asyncio
import sys
from pathlib import Path

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.explain import ask
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL
from ai_teacher_api.director.agent import INSTRUCTION


def explain_director(d: Path, lesson_id: str, out_id: str, question: str, model: str = DEFAULT_TEXT_MODEL) -> str:
    md = (d / "illustrated" / f"{lesson_id}-final" / "lecture.md").read_text()
    directed = (d / f"directed-{out_id}.json").read_text()
    answer, _ = asyncio.run(with_model_fallback(lambda m: ask(INSTRUCTION, md, directed, question, m), model))
    logsetup.get("director").info("explanation", lesson=out_id, question=question, answer=answer)
    return answer


if __name__ == "__main__":
    print(explain_director(Path(sys.argv[1]), sys.argv[2], f"{sys.argv[2]}-v2", sys.argv[3]))
