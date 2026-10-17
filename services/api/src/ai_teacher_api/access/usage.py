"""Who is paying for this call? A context variable carries the signed-in user from the request into every model call, including background jobs
(teacher.jobs copies the context into its thread). The google-genai SDK is wrapped ONCE here (install()), so every call made through it, by our code or by ADK,
is checked before it runs (credit left? cap reached?) and charged after it returns. Code with no user (command line runs) is neither checked nor charged."""

import asyncio
import contextlib
import contextvars
import functools

from ai_teacher_api.access import credits, pricing
from ai_teacher_api.common import logsetup

log = logsetup.get("app")
_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("access_user", default=None)
_installed = False


def current() -> dict | None:
    return _user.get()


def set_user(email: str | None, unlimited: bool = False) -> contextvars.Token:
    return _user.set({"email": email, "unlimited": unlimited} if email else None)


@contextlib.contextmanager
def bind(email: str | None, unlimited: bool = False):
    tok = set_user(email, unlimited)
    try:
        yield
    finally:
        _user.reset(tok)


def precheck() -> None:
    u = _user.get()
    if u and u["email"]:
        credits.check(u["email"])


def charge(micro: int, kind: str, model: str = "", detail: str = "", counter: str = "", counter_n: int = 0) -> None:
    u = _user.get()
    if u and u["email"]:
        try:
            credits.spend(u["email"], micro, kind, model, detail, counter, counter_n)
        except Exception as e:  # noqa: BLE001 - a failing ledger must not break a class that is already running
            log.error("charge-failed", email=u["email"], micro=micro, kind=kind, error=repr(e)[:200])


def _model_of(args, kwargs) -> str:
    return str(kwargs.get("model") or (args[0] if args else ""))


def wrap_sync(orig):
    @functools.wraps(orig)
    def f(self, *a, **kw):
        precheck()
        r = orig(self, *a, **kw)
        charge(pricing.response_cost(_model_of(a, kw), r), "model", _model_of(a, kw))
        return r

    return f


def wrap_sync_stream(orig):
    @functools.wraps(orig)
    def f(self, *a, **kw):
        precheck()
        last = None
        for chunk in orig(self, *a, **kw):
            if getattr(chunk, "usage_metadata", None):
                last = chunk
            yield chunk
        if last is not None:
            charge(pricing.response_cost(_model_of(a, kw), last), "model", _model_of(a, kw))

    return f


def wrap_async(orig):
    @functools.wraps(orig)
    async def f(self, *a, **kw):
        await asyncio.to_thread(precheck)
        r = await orig(self, *a, **kw)
        await asyncio.to_thread(charge, pricing.response_cost(_model_of(a, kw), r), "model", _model_of(a, kw))
        return r

    return f


def wrap_async_stream(orig):
    @functools.wraps(orig)
    async def f(self, *a, **kw):
        await asyncio.to_thread(precheck)
        stream = await orig(self, *a, **kw)

        async def gen():
            last = None
            async for chunk in stream:
                if getattr(chunk, "usage_metadata", None):
                    last = chunk
                yield chunk
            if last is not None:
                await asyncio.to_thread(charge, pricing.response_cost(_model_of(a, kw), last), "model", _model_of(a, kw))

        return gen()

    return f


def install() -> None:
    """Wrap generate_content / generate_content_stream (sync and async) of the google-genai SDK. Safe to call twice."""
    global _installed
    if _installed:
        return
    _installed = True
    from google.genai import models as gm

    gm.Models.generate_content = wrap_sync(gm.Models.generate_content)
    gm.Models.generate_content_stream = wrap_sync_stream(gm.Models.generate_content_stream)
    gm.AsyncModels.generate_content = wrap_async(gm.AsyncModels.generate_content)
    gm.AsyncModels.generate_content_stream = wrap_async_stream(gm.AsyncModels.generate_content_stream)
