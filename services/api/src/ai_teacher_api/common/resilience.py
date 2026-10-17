"""Quota handling: when a model returns 429 RESOURCE_EXHAUSTED, try the next model instead of waiting."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ai_teacher_api.common.settings import FALLBACK_MODELS, resolve_model

T = TypeVar("T")


TRANSIENT = ("RESOURCE_EXHAUSTED", "429", "UNAVAILABLE", "503", "INTERNAL", "DEADLINE_EXCEEDED", "Timeout")


def is_quota_error(e: BaseException) -> bool:
    """Quota or transient server trouble: either way the next model may work."""
    return any(k in repr(e) for k in TRANSIENT)


async def with_model_fallback(
    fn: Callable[[str], Awaitable[T]], model: str | None, rounds: int = 3, wait: float = 30.0
) -> tuple[T, str]:
    """Run fn(model); on a quota error go to the next model in the chain. After the whole chain has
    failed, wait (growing) and go round again. Returns (result, model_used)."""
    first = resolve_model(model)
    chain = [first] + [m for m in FALLBACK_MODELS if m != first]
    for r in range(rounds):
        for m in chain:
            try:
                return await fn(m), m
            except Exception as e:  # noqa: BLE001 - ADK wraps the 429 in its own error types
                if not is_quota_error(e):
                    raise
                print(f"[retry] {m} unavailable/rate limited ({type(e).__name__}), trying the next model", file=sys.stderr, flush=True)
        delay = wait * (r + 1)
        print(f"[429] every model limited, waiting {delay:.0f}s (round {r + 1}/{rounds})", file=sys.stderr, flush=True)
        await asyncio.sleep(delay)
    raise RuntimeError("all models stayed rate limited; try again later")
