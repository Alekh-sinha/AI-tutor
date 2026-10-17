"""Background jobs started from the dashboard (generate a lesson, parse+plan a new chapter). One image-using job at a time (see common.workspace).
Each job's stages and failures are logged to logs/content.jsonl with the job id, and the dashboard polls `GET /teacher/jobs/{id}`."""

import threading
import time
import traceback
import uuid
from collections.abc import Callable

from ai_teacher_api.common import logsetup, workspace

log = logsetup.get("content")
JOBS: dict[str, dict] = {}


def start(kind: str, label: str, fn: Callable[[Callable[[str], None]], dict], needs_images: bool = True) -> dict:
    """Run fn(progress) in a thread. Returns the job record, or raises RuntimeError when another image job is running."""
    jid = uuid.uuid4().hex[:8]
    if needs_images and not workspace.try_acquire(f"job {jid} {label}"):
        raise RuntimeError(f"busy: {workspace.holder['who']}")
    job = {"id": jid, "kind": kind, "label": label, "status": "running", "stage": "starting", "started": time.time(), "ended": None, "error": "", "result": None}
    JOBS[jid] = job
    log.info("job-start", job=jid, kind=kind, label=label)

    def progress(stage: str) -> None:
        job["stage"] = stage
        log.info("job-stage", job=jid, stage=stage, seconds=round(time.time() - job["started"]))

    def run() -> None:
        status, error, result = "done", "", None
        try:
            result = fn(progress)
        except Exception as e:  # noqa: BLE001
            status, error = "failed", repr(e)[:400]
            log.error("job-failed", job=jid, label=label, error=error, trace=traceback.format_exc()[-1500:])
        finally:
            if needs_images:
                workspace.release()  # before the status flips, so a client that sees "done" can start the next job
        job.update(result=result, error=error, ended=time.time(), status=status)
        if status == "done":
            log.info("job-done", job=jid, seconds=round(time.time() - job["started"]), result=result)

    threading.Thread(target=run, daemon=True, name=f"job-{jid}").start()
    return job


def get(jid: str) -> dict | None:
    return JOBS.get(jid)


def running(label_prefix: str = "") -> list[dict]:
    return [j for j in JOBS.values() if j["status"] == "running" and j["label"].startswith(label_prefix)]
