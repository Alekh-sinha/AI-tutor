import json
from pathlib import Path

from ai_teacher_api.common.lesson import Lesson

OUT = Path(__file__).resolve().parents[5] / "packages/lesson-schema/lesson.schema.json"


def main() -> None:
    OUT.write_text(json.dumps(Lesson.model_json_schema(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
