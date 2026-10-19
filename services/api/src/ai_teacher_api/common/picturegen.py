"""Reentrant picture drawing for LIVE classes: no global state, no lock (unlike authoring/illustrator.py, whose folder/budget are process-wide and need common/workspace.py), so a class never has to
give up its pictures because a dashboard job is running.
Rate limit: each image model has its OWN quota bucket of 2 requests per minute (measured 2026-10-15: 3 parallel calls to one model -> 429 for the extra ones, while a second model accepted its two at the same moment).
`draw` picks whichever model has room, waits when both are full, and on a 429 blocks that model for a while and tries the other. POOL = the models we can call today: gemini-3.1-flash-image only exists at `global`,
gemini-2.5-flash-image (retires 2027-03-15) at us-central1 (and other regions). Raising the console quota (only the regional row is adjustable) multiplies PER_WINDOW for the regional model."""

import asyncio
import io
import time
from collections import deque
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from ai_teacher_api.authoring.illustrator import STYLE
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import PROJECT

log = logsetup.get("live")
POOL = [("gemini-3.1-flash-image", "global"), ("gemini-2.5-flash-image", "us-central1")]
WINDOW = 60.0
PER_WINDOW = 2  # requests per model per minute (the default quota)
BLOCK_AFTER_429 = 30.0
ATTEMPTS = 8

_now = time.monotonic  # replaced in tests
_sleep = asyncio.sleep


class _Bucket:
    def __init__(self, model: str, location: str) -> None:
        self.model, self.location = model, location
        self.stamps: deque[float] = deque()
        self.blocked_until = 0.0

    def free_at(self, now: float) -> float:
        """When this model can take one more request (<= now means: now)."""
        while self.stamps and self.stamps[0] <= now - WINDOW:
            self.stamps.popleft()
        at = self.stamps[0] + WINDOW if len(self.stamps) >= PER_WINDOW else now
        return max(at, self.blocked_until, now)


_buckets = [_Bucket(m, l) for m, l in POOL]
_lock: asyncio.Lock | None = None


async def reserve() -> _Bucket:
    """The model that can take a request soonest (waiting if every bucket is full); counts the request against it."""
    global _lock
    _lock = _lock or asyncio.Lock()
    while True:
        async with _lock:
            now = _now()
            best = min(_buckets, key=lambda b: b.free_at(now))
            at = best.free_at(now)
            if at <= now:
                best.stamps.append(now)
                return best
            wait = at - now
        await _sleep(min(wait, 5.0) + 0.1)


def wait_seconds() -> float:
    """How long until some image model has room for one more request (0 = now). Does not reserve anything: lets a caller decide to go without a picture instead of queueing."""
    now = _now()
    return max(0.0, min(b.free_at(now) for b in _buckets) - now)


def _save(data: bytes, path: Path) -> None:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((768, 768))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "WEBP", quality=75)


async def draw(description: str, path: Path, style: str = STYLE) -> dict:
    """Draw one picture (default style: realistic photograph; `style` is the text put before the description) and save it as WebP at `path`. Returns {"status": "ok", "model", "seconds"} or {"status": "error", "error"}."""
    t0, last = _now(), ""
    for attempt in range(1, ATTEMPTS + 1):
        b = await reserve()
        client = genai.Client(vertexai=True, project=PROJECT, location=b.location)
        try:
            r = await client.aio.models.generate_content(model=b.model, contents=style + description, config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
            images = [p for p in r.candidates[0].content.parts if p.inline_data and p.inline_data.mime_type.startswith("image/")]
            if not images:
                last = "the model returned no image"
                log.warn("picture-no-image", model=b.model, attempt=attempt, description=description[:120])
                continue
            await asyncio.to_thread(_save, images[-1].inline_data.data, path)
            log.info("picture-drawn", model=b.model, attempt=attempt, seconds=round(_now() - t0, 1), path=path.name)
            return {"status": "ok", "model": b.model, "seconds": round(_now() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
            if "429" in last or "RESOURCE_EXHAUSTED" in last:
                b.blocked_until = _now() + BLOCK_AFTER_429  # this model's bucket is full: use the other one meanwhile
                log.warn("picture-429", model=b.model, attempt=attempt)
            elif any(k in last for k in ("503", "UNAVAILABLE", "INTERNAL", "DEADLINE", "timed out")):
                await _sleep(5)
            else:
                log.error("picture-failed", model=b.model, error=last)
                break
    return {"status": "error", "error": last}
