"""The deployed service: ONE process, ONE address. `/api/*` is the API (app.py), `/lessons`, `/audio`, `/img`, `/chat` are the player's files (guarded by access/library.py),
and everything else is the built web app (apps/web/dist) with index.html as the fallback for client-side pages.
Start: `uvicorn ai_teacher_api.server:root --port 8080` (the container does this). Development keeps using `uvicorn ai_teacher_api.app:app` + Vite."""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from ai_teacher_api.access import library
from ai_teacher_api.app import app as api
from ai_teacher_api.common.settings import WEB_PUBLIC

root = FastAPI(title="Seekho Saathi", docs_url=None, redoc_url=None)
DIST = WEB_PUBLIC.parent / "dist"


@root.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


root.include_router(library.router)
root.mount("/api", api)
for sub in ("img", "chat"):
    (WEB_PUBLIC / sub).mkdir(parents=True, exist_ok=True)
    root.mount(f"/{sub}", StaticFiles(directory=WEB_PUBLIC / sub), name=sub)


class Spa(StaticFiles):
    """Files of the built app; any other path returns index.html so a reload of /teacher or /?live=1 works."""

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404 and not path.startswith(("api/", "lessons/", "audio/", "img/")):
                return FileResponse(DIST / "index.html")
            raise


if DIST.exists():
    root.mount("/", Spa(directory=DIST, html=True), name="web")
