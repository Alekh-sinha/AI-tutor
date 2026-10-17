"""The image tools (authoring.illustrator) keep process-wide state (current picture folder, budget). Anything that draws or edits pictures must hold this lock,
so a generation job, a teacher edit and a student's drawn picture can never write into each other's folders."""

import threading

image_lock = threading.Lock()
holder = {"who": ""}


def try_acquire(who: str) -> bool:
    if image_lock.acquire(blocking=False):
        holder["who"] = who
        return True
    return False


def release() -> None:
    holder["who"] = ""
    if image_lock.locked():
        image_lock.release()
