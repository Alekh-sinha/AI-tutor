"""Whose chapter is it? Chapters made by a signed-in user get the id prefix `u<hash of the email>-`, so ownership needs no lookup: the id itself says whose it is.
Chapters without the prefix (the first book, `ch6`) belong to the admin. The signed-in user of the current request comes from the usage context.
With AUTH_MODE=off (local development, command line tools) nothing is restricted."""

import hashlib
import os
import re

from fastapi import HTTPException

from ai_teacher_api.access import credits, usage

PREFIX = re.compile(r"^u[0-9a-f]{8}-")


def prefix_for(email: str) -> str:
    return "u" + hashlib.sha1(email.lower().encode()).hexdigest()[:8] + "-"


def restricted() -> bool:
    return os.environ.get("AUTH_MODE", "off") == "on"


def can_access(chapter_or_lesson_id: str, email: str | None) -> bool:
    if not restricted():
        return True
    if not email:
        return False
    if credits.is_admin(email):
        return True
    return chapter_or_lesson_id.startswith(prefix_for(email))


def require(chapter: str) -> None:
    """Raise 404 (not 403: do not reveal what exists) unless the current user may use this chapter."""
    if not restricted():
        return
    u = usage.current()
    if not can_access(chapter, u["email"] if u else None):
        raise HTTPException(404, "unknown chapter")


def chapter_of_lesson_id(pid: str) -> str:
    """The chapter a player lesson id belongs to: `u1234abcd-ch2-lesson-1-v2(-draft)` -> `u1234abcd-ch2`; `lesson-1-v2` -> the default chapter."""
    from ai_teacher_api.common.paths import split_public_id

    pid = re.sub(r"-draft$", "", pid)
    return split_public_id(pid)[0]
