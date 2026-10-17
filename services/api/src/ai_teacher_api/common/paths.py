"""Where chapters live and how lessons are named. A chapter is a folder `data/<chapter>/` (chapter.json, plan.json, brief-<lesson>.json, illustrated/<lesson>-final/ ...).
Published (player) lesson ids: `<lesson>-v2` for the default chapter, `<chapter>-<lesson>-v2` for others, so the first chapter's links keep working."""

import re

from fastapi import HTTPException

from ai_teacher_api.common.settings import CHAPTER_DIR

DATA_DIR = CHAPTER_DIR.parent
DEFAULT_CHAPTER = CHAPTER_DIR.name
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def chapter_dir(chapter: str, must_exist: bool = True):
    if not NAME.match(chapter):
        raise HTTPException(400, "bad chapter id")
    d = DATA_DIR / chapter
    if must_exist and not (d / "plan.json").exists():
        raise HTTPException(404, "unknown chapter (no plan.json yet)")
    return d


def public_id(chapter: str, lesson: str) -> str:
    return f"{lesson}-v2" if chapter == DEFAULT_CHAPTER else f"{chapter}-{lesson}-v2"


def split_public_id(pid: str) -> tuple[str, str]:
    """(chapter, lesson) of a player lesson id such as `lesson-2-v2`, `ch7-lesson-1-v2` or the classic `lesson-3`."""
    m = re.match(r"^(?:(?P<ch>[A-Za-z0-9_]+)-)?(?P<lesson>lesson-\d+)(?:-v\d+)?$", pid)
    return (m.group("ch") or DEFAULT_CHAPTER, m.group("lesson")) if m else (DEFAULT_CHAPTER, pid)
