"""Live versus draft of a PUBLISHED lesson. Students watch the live files (`<pid>.json`, `<pid>.mp3`, `<pid>-<picture>.webp`). Once a lesson has been published,
every edit (lecture or video) is built as a hidden DRAFT (`<pid>-draft…`) and reaches students only when the teacher presses "Publish changes".
State per lesson: `publish-state-<pid>.json` = {version, lecture_sha, script_sha}: what is live now (also a copy of the live script, for "discard draft")."""

import hashlib
import json
import shutil
import time
from pathlib import Path

from ai_teacher_api.common.settings import WEB_PUBLIC


def _state(d: Path, pid: str) -> Path:
    return d / f"publish-state-{pid}.json"


def _live_script(d: Path, pid: str) -> Path:
    return d / f"directed-live-{pid}.json"


def sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def get(d: Path, pid: str) -> dict | None:
    f = _state(d, pid)
    return json.loads(f.read_text()) if f.exists() else None


def is_live(d: Path, pid: str) -> bool:
    """Has this lesson been published (students can watch it)? Lessons published before this feature existed count too (index status)."""
    if get(d, pid):
        return True
    idx = WEB_PUBLIC / "lessons" / "index.json"
    try:
        return any(e["id"] == pid and e.get("status") == "published" for e in json.loads(idx.read_text()))
    except (OSError, ValueError):
        return False


def draft_id(pid: str) -> str:
    return f"{pid}-draft"


def build_id(d: Path, pid: str) -> str:
    """Which player id a rebuild writes to: the live one while the lesson is unpublished, the hidden draft once it is live."""
    return draft_id(pid) if is_live(d, pid) else pid


def mark_published(d: Path, pid: str, lecture_md: str, script_json: str) -> dict:
    prev = get(d, pid) or {"version": 0}
    st = {"version": prev["version"] + 1, "lecture_sha": sha(lecture_md), "script_sha": sha(script_json), "at": time.time()}
    _state(d, pid).write_text(json.dumps(st))
    _live_script(d, pid).write_text(script_json)
    _drop_draft_files(pid)
    return st


def mark_video_published(d: Path, pid: str, script_json: str) -> dict:
    """The video draft went live: new version, same lecture (the lecture hash stays what it was when it last went live)."""
    prev = get(d, pid) or {"version": 1, "lecture_sha": ""}
    st = {**prev, "version": prev["version"] + 1, "script_sha": sha(script_json), "at": time.time()}
    _state(d, pid).write_text(json.dumps(st))
    _live_script(d, pid).write_text(script_json)
    _drop_draft_files(pid)
    return st


def status(d: Path, pid: str, lecture_md: str, script_json: str | None) -> dict:
    """What the dashboard shows: live version and whether a draft differs from it."""
    st = get(d, pid)
    live = is_live(d, pid)
    if not live:
        return {"live": False, "version": 0, "lecture_changed": False, "video_changed": False, "draft_ready": False}
    version = st["version"] if st else 1
    lecture_changed = bool(st) and sha(lecture_md) != st["lecture_sha"]
    video_changed = bool(st and script_json) and sha(script_json) != st["script_sha"]
    return {"live": True, "version": version, "lecture_changed": lecture_changed, "video_changed": video_changed,
            "draft_ready": (WEB_PUBLIC / "lessons" / f"{draft_id(pid)}.json").exists()}


def _drop_draft_files(pid: str) -> None:
    did = draft_id(pid)
    (WEB_PUBLIC / "lessons" / f"{did}.json").unlink(missing_ok=True)
    (WEB_PUBLIC / "audio" / f"{did}.mp3").unlink(missing_ok=True)
    for f in (WEB_PUBLIC / "img").glob(f"{did}-*.webp"):
        f.unlink(missing_ok=True)


def publish_draft(d: Path, pid: str) -> dict:
    """Copy the built draft over the live files (pictures and audio first, the lesson JSON last, so a student never sees a half-copied lesson)."""
    did = draft_id(pid)
    src_json = WEB_PUBLIC / "lessons" / f"{did}.json"
    if not src_json.exists():
        raise FileNotFoundError("the draft video is not built yet")
    for f in (WEB_PUBLIC / "img").glob(f"{did}-*.webp"):
        shutil.copy(f, f.with_name(f.name.replace(did, pid, 1)))
    shutil.copy(WEB_PUBLIC / "audio" / f"{did}.mp3", WEB_PUBLIC / "audio" / f"{pid}.mp3")
    text = src_json.read_text().replace(did, pid)
    tmp = WEB_PUBLIC / "lessons" / f"{pid}.json.tmp"
    tmp.write_text(text)
    tmp.replace(WEB_PUBLIC / "lessons" / f"{pid}.json")
    return {"script": (d / f"directed-{pid}.json").read_text()}


def discard_draft(d: Path, pid: str) -> None:
    """Throw the draft video away: the working script returns to what is live."""
    live = _live_script(d, pid)
    if live.exists():
        shutil.copy(live, d / f"directed-{pid}.json")
    _drop_draft_files(pid)
