import asyncio

from ai_teacher_api.common import picturegen as pg


def fresh(monkeypatch):
    clock = {"t": 1000.0}
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        clock["t"] += s

    monkeypatch.setattr(pg, "_now", lambda: clock["t"])
    monkeypatch.setattr(pg, "_sleep", fake_sleep)
    monkeypatch.setattr(pg, "_lock", None)
    monkeypatch.setattr(pg, "_buckets", [pg._Bucket("a", "global"), pg._Bucket("b", "us-central1")])
    return clock, sleeps


def test_two_models_take_four_requests_at_once_then_the_fifth_waits(monkeypatch):
    clock, sleeps = fresh(monkeypatch)

    async def go():
        got = [(await pg.reserve()).model for _ in range(4)]
        assert sorted(got) == ["a", "a", "b", "b"] and not sleeps  # 2 per model per minute, no waiting
        t0 = clock["t"]
        await pg.reserve()
        assert sleeps and clock["t"] - t0 >= pg.WINDOW - 1  # the fifth request waits for a bucket to free up

    asyncio.run(go())


def test_a_blocked_model_is_skipped_for_the_other(monkeypatch):
    clock, sleeps = fresh(monkeypatch)
    pg._buckets[0].blocked_until = clock["t"] + 30  # model a just returned a 429

    async def go():
        got = [(await pg.reserve()).model for _ in range(2)]
        assert got == ["b", "b"] and not sleeps

    asyncio.run(go())
