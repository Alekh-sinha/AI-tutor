"""Server-sent events that survive proxies: a quiet stream is cut by many proxies and load balancers after 30-60 s, so a comment line (`: ping`) is sent every 15 s while we wait."""

import asyncio
import json
import time

PING_EVERY = 15.0


async def events(queue: asyncio.Queue, total_timeout: float):
    """Yield SSE text for every queued event until {"type": "done"}; ping while idle; stop after total_timeout seconds."""
    deadline = time.monotonic() + total_timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise asyncio.TimeoutError
        try:
            ev = await asyncio.wait_for(queue.get(), timeout=min(PING_EVERY, left))
        except asyncio.TimeoutError:
            if time.monotonic() >= deadline:
                raise
            yield ": ping\n\n"
            continue
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if ev["type"] == "done":
            return
