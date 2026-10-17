"""API entry point: only assembles the feature routers. Each feature lives in its own package (and logs to logs/<feature>.jsonl):
tutor/ (student chat + turn-based live class), live/ (streaming live class for a room of children), teacher/ (dashboard, editing agent, publish, generate), director/ (Agent 2 + assembly), authoring/ (Agent 1 + review/edit loop),
content/ (PDF -> plan -> lessons pipeline), classic/ (the older scripter pipeline), common/ (settings, schema, logging)."""

import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from ai_teacher_api.common import logsetup, tracing
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, DEFAULT_VOICE, TEXT_MODELS, VOICES
from ai_teacher_api.live import routes as live_routes
from ai_teacher_api.teacher import routes as teacher
from ai_teacher_api.teacher import video as teacher_video
from ai_teacher_api.tutor import routes as tutor_routes

tracing.init()  # Langfuse traces of every chat / editing turn (no-op without keys)
app = FastAPI(title="AI Teacher API")


class PicturesOnly(StaticFiles):
    """Serve only the lecture pictures (`<chapter>/illustrated/<lesson>-final/**.webp`), not source PDFs, drafts or anything else under data/."""

    async def get_response(self, path, scope):
        parts = path.split("/")
        if len(parts) < 4 or parts[1] != "illustrated" or not path.endswith(".webp") or ".." in parts:
            raise HTTPException(404)
        return await super().get_response(path, scope)


app.mount("/files", PicturesOnly(directory=teacher.ILLUSTRATED), name="files")  # lecture pictures for the teacher dashboard
app.include_router(teacher.router)
app.include_router(teacher_video.router)
app.include_router(tutor_routes.router)
app.include_router(live_routes.router)
logsetup.get("app").info("startup")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
def models() -> dict:
    """Text models the UI can offer for generation; the choice is passed per job."""
    return {"default": DEFAULT_TEXT_MODEL, "models": [{"id": k, "label": v} for k, v in TEXT_MODELS.items()]}


@app.get("/voices")
def voices() -> dict:
    return {"default": DEFAULT_VOICE, "voices": [{"id": k, "label": v} for k, v in VOICES.items()]}


@app.get("/debug/logs/{feature}")
def debug_logs(feature: str, n: int = 100, level: str | None = None, x_teacher_token: str | None = Header(None)) -> list[dict]:
    """Recent structured log events of one feature (tutor, teacher, director, authoring, content, classic, app). Protected by TEACHER_TOKEN when set."""
    import os

    token = os.environ.get("TEACHER_TOKEN")
    if token and x_teacher_token != token:
        raise HTTPException(401, "token required")
    if feature not in logsetup.FEATURES:
        raise HTTPException(404, "unknown feature")
    return logsetup.tail(feature, min(n, 500), level)


class ClientLog(BaseModel):
    message: str = Field(max_length=500)
    stack: str = Field("", max_length=1500)
    url: str = Field("", max_length=300)
    kind: str = Field("error", max_length=20)


_client_log_times: list[float] = []


@app.post("/client-log")
def client_log(body: ClientLog) -> dict[str, str]:
    """The browser reports JavaScript errors here (logs/app.jsonl, event `client-error`), so a broken screen leaves evidence. Limited to 60 reports a minute."""
    now = time.time()
    _client_log_times[:] = [t for t in _client_log_times if now - t < 60]
    if len(_client_log_times) < 60:
        _client_log_times.append(now)
        logsetup.get("app").error("client-error", message=body.message, stack=body.stack, url=body.url, kind=body.kind)
    return {"status": "ok"}
