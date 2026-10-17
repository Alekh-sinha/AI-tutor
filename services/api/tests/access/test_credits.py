import asyncio
import contextvars
import threading
from types import SimpleNamespace as NS

import pytest

from ai_teacher_api.access import credits, pricing, usage
from ai_teacher_api.access.store import MemoryStore, set_store


@pytest.fixture(autouse=True)
def fresh_store():
    set_store(MemoryStore())
    yield


def resp(prompt=1000, out=500, images=0):
    parts = [NS(inline_data=NS(mime_type="image/png"))] * images
    return NS(usage_metadata=NS(prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=0, tool_use_prompt_token_count=0),
              candidates=[NS(content=NS(parts=parts), grounding_metadata=None)])


def test_new_user_is_pending_and_admin_is_active():
    u = credits.login("kid@example.com", "Kid")
    assert u["status"] == "pending" and u["credit_micro"] == 0
    a = credits.login("alekh.sinha09@gmail.com")
    assert a["role"] == "admin" and a["status"] == "active"
    with pytest.raises(credits.NotApproved):
        credits.check("kid@example.com")
    credits.check("alekh.sinha09@gmail.com")  # admin is never refused


def test_grant_activates_and_spend_reduces_balance_until_exhausted():
    credits.login("a@x.com")
    credits.grant("a@x.com", 1.0, by="admin")
    credits.check("a@x.com")
    credits.spend("a@x.com", 600_000, "model", "m")
    assert credits.view(credits.get("a@x.com"))["balance_usd"] == 0.4
    credits.spend("a@x.com", 500_000, "model", "m")
    with pytest.raises(credits.CreditExhausted):
        credits.check("a@x.com")


def test_daily_cap_blocks_even_with_credit_left():
    credits.login("a@x.com")
    credits.grant("a@x.com", 10.0, by="admin")
    credits.set_daily_cap("a@x.com", 1.0)
    credits.spend("a@x.com", 1_000_000, "model")
    with pytest.raises(credits.DailyCapReached):
        credits.check("a@x.com")


def test_blocked_user_is_refused():
    credits.login("a@x.com")
    credits.grant("a@x.com", 5, by="admin")
    credits.set_status("a@x.com", "blocked")
    with pytest.raises(credits.Blocked):
        credits.check("a@x.com")


def test_prices():
    assert pricing.response_cost("gemini-3.6-flash", resp(1_000_000, 0)) == round(0.75 * 1e6 * pricing.MARGIN)
    assert pricing.response_cost("gemini-3.1-flash-image", resp(0, 0, images=2)) == round(2 * 0.067 * 1e6 * pricing.MARGIN)
    assert pricing.response_cost("some-new-model", resp(1_000_000, 0)) == round(2.0 * 1e6 * pricing.MARGIN)  # never free


def test_two_users_at_once_are_charged_separately_and_exactly():
    """Two users run model calls at the same moment from threads and from async tasks: every ledger adds up to that user's own calls."""
    for e in ("a@x.com", "b@x.com"):
        credits.login(e)
        credits.grant(e, 100, by="admin")

    def fake_sync(self, *a, **kw):
        return resp(1000, 100)

    async def fake_async(self, *a, **kw):
        await asyncio.sleep(0.001)
        return resp(2000, 200)

    sync_call, async_call = usage.wrap_sync(fake_sync), usage.wrap_async(fake_async)
    cost_s = pricing.response_cost("m", resp(1000, 100))
    cost_a = pricing.response_cost("m", resp(2000, 200))

    def worker_sync(email, n):
        ctx = contextvars.copy_context()

        def run():
            usage.set_user(email)
            for _ in range(n):
                sync_call(None, model="m")

        t = threading.Thread(target=ctx.run, args=(run,))
        t.start()
        return t

    async def worker_async(email, n):
        usage.set_user(email)
        for _ in range(n):
            await async_call(None, model="m")

    async def main():
        threads = [worker_sync("a@x.com", 30), worker_sync("b@x.com", 10)]
        await asyncio.gather(
            asyncio.create_task(worker_async("a@x.com", 20)),
            asyncio.create_task(worker_async("b@x.com", 40)),
        )
        for t in threads:
            await asyncio.to_thread(t.join)

    asyncio.run(main())
    a, b = credits.get("a@x.com"), credits.get("b@x.com")
    assert a["spent_micro"] == 30 * cost_s + 20 * cost_a
    assert b["spent_micro"] == 10 * cost_s + 40 * cost_a
    from ai_teacher_api.access.store import get_store

    assert sum(r["micro"] for r in get_store().query("ledger", {"email": "a@x.com", "kind": "model"}, limit=1000)) == a["spent_micro"]


def test_exhausted_user_cannot_start_a_call():
    credits.login("a@x.com")
    credits.grant("a@x.com", 0.0001, by="admin")
    credits.spend("a@x.com", 500, "model")
    called = []
    f = usage.wrap_sync(lambda self, *a, **kw: called.append(1) or resp())
    usage.set_user("a@x.com")
    with pytest.raises(credits.CreditExhausted):
        f(None, model="m")
    assert not called
    usage.set_user(None)
    f(None, model="m")  # no user (command line): not checked
    assert called
