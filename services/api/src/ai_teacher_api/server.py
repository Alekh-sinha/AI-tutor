"""The deployed service: ONE process, ONE address. `/api/*` is the API (app.py), `/lessons`, `/audio`, `/img`, `/chat` are the player's files (guarded by access/library.py),
and everything else is the built web app (apps/web/dist) with index.html as the fallback for client-side pages.
Start: `uvicorn ai_teacher_api.server:root --port 8080` (the container does this). Development keeps using `uvicorn ai_teacher_api.app:app` + Vite."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import Scope

from ai_teacher_api.access import library
from ai_teacher_api.app import app as api
from ai_teacher_api.common import persist
from ai_teacher_api.common.settings import WEB_PUBLIC

@asynccontextmanager
async def lifespan(_: FastAPI):
    """With DATA_BUCKET set: restore the files from the bucket before serving, push changes while running and once more on shutdown."""
    import asyncio

    import os

    from ai_teacher_api.access import credits

    if persist.configure():
        await asyncio.to_thread(persist.start)
    if os.environ.get("STORE") == "firestore":
        credits.enable_batching()  # spends are summed and written once a second per user
    yield
    await asyncio.to_thread(credits.flush)
    await asyncio.to_thread(persist.stop)


root = FastAPI(title="Seekho Saathi", docs_url=None, redoc_url=None, lifespan=lifespan)
DIST = WEB_PUBLIC.parent / "dist"


@root.get("/ping")
def ping() -> dict:
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
            if e.status_code == 404 and "." not in path.rsplit("/", 1)[-1] and not path.startswith(("api/", "lessons/", "audio/", "img/")):
                return FileResponse(DIST / "index.html")
            raise


if DIST.exists():
    root.mount("/", Spa(directory=DIST, html=True), name="web")
