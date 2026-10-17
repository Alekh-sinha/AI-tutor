"""Who may see which lesson. The player reads `/lessons/index.json`, `/lessons/<id>.json` and `/audio/<id>.mp3`; in the deployed service these come from here
instead of plain static files, so a draft is visible only to its owner and the admin. The PUBLIC lessons (chosen by the admin, `data/public-lessons.json`) are
watchable by anyone, even without signing in, and never cost anything: they are plain files, no model is involved.
In development (Vite) the same URLs are served as static files from apps/web/public, unguarded (AUTH_MODE=off)."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ai_teacher_api.access import auth, credits, ownership
from ai_teacher_api.common.paths import DATA_DIR
from ai_teacher_api.common.settings import WEB_PUBLIC

router = APIRouter()
PUBLIC_FILE = DATA_DIR / "public-lessons.json"
ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def public_ids() -> list[str]:
    try:
        return json.loads(PUBLIC_FILE.read_text())
    except (OSError, ValueError):
        return []


def set_public_ids(ids: list[str]) -> None:
    PUBLIC_FILE.write_text(json.dumps(sorted(set(ids)), indent=1))


def can_see(lesson_id: str, user: dict | None) -> bool:
    if lesson_id in public_ids():
        return True
    if not ownership.restricted():
        return True
    return ownership.can_access(ownership.chapter_of_lesson_id(lesson_id), user["email"] if user else None) and (user is not None and user["status"] == "active")


@router.get("/lessons/index.json")
async def index(u: dict | None = Depends(auth.optional_user)):
    f = WEB_PUBLIC / "lessons" / "index.json"
    entries = json.loads(f.read_text()) if f.exists() else []
    pub = set(public_ids())
    out = []
    for e in entries:
        if e["id"].endswith("-draft"):
            continue
        if can_see(e["id"], u):
            out.append({**e, "public": e["id"] in pub})
    return JSONResponse(out, headers={"cache-control": "no-store"})


@router.get("/lessons/{lesson_id}.json")
async def lesson_json(lesson_id: str, u: dict | None = Depends(auth.optional_user)):
    f = WEB_PUBLIC / "lessons" / f"{lesson_id}.json"
    if not ID.match(lesson_id) or not f.exists():
        raise HTTPException(404, "no such lesson")
    if not can_see(lesson_id, u):
        raise HTTPException(401 if u is None else 403, {"code": "sign_in" if u is None else "no_access", "message": "Please sign in to watch this lesson." if u is None else "This lesson is not shared with you."})
    return FileResponse(f, headers={"cache-control": "no-store"})


@router.get("/audio/{name}")
async def audio(name: str, u: dict | None = Depends(auth.optional_user)):
    stem = name.removesuffix(".mp3")
    f = WEB_PUBLIC / "audio" / f"{stem}.mp3"
    if not ID.match(stem) or not f.exists():
        raise HTTPException(404, "no such audio")
    if not can_see(stem, u):
        raise HTTPException(401 if u is None else 403, "not allowed")
    return FileResponse(f, media_type="audio/mpeg")
