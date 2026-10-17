import asyncio
import time

import pytest

from ai_teacher_api.live import room as R


def mk(n, room=None):
    room = room or R.Room(code="1", host_key="k")
    sent = []

    async def send(ev):
        sent.append(ev)

    async def sb(b):
        sent.append(b)

    for i in range(n):
        room.add(R.Member(id=f"m{i}", name=f"c{i}", send=send, send_bytes=sb, is_host=i == 0))
    return room, sent


def test_solo_room_floor_is_always_open():
    r, _ = mk(1)
    assert r.may_speak("m0")
    assert r.grant_next() == "m0"


def test_hands_are_served_in_order_one_at_a_time():
    r, _ = mk(3)
    r.raise_hand("m2"); r.raise_hand("m1"); r.raise_hand("m2")  # a second raise does nothing
    assert r.queue == ["m2", "m1"]
    assert r.grant_next() == "m2" and r.may_speak("m2") and not r.may_speak("m1")
    assert r.grant_next() == "m1" and not r.may_speak("m2")
    assert r.grant_next() is None and not r.may_speak("m1")


def test_leaving_child_loses_hand_and_floor():
    r, _ = mk(3)
    r.raise_hand("m1"); r.raise_hand("m2")
    r.grant_next()
    r.remove("m1")
    assert r.floor is None
    r.remove("m2")
    assert r.queue == []


def test_unused_floor_expires_only_with_several_children():
    r, _ = mk(2)
    r.raise_hand("m1"); r.grant_next()
    r.floor_since = time.time() - R.FLOOR_TIMEOUT - 1
    assert r.floor_expired()
    solo, _ = mk(1)
    solo.floor, solo.floor_since = "m0", time.time() - 999
    assert not solo.floor_expired()


def test_state_hides_nothing_needed_and_snapshot_has_board():
    r, _ = mk(2)
    r.board.append({"type": "note", "id": "n1", "text": "x"})
    assert "board" not in r.public_state() and r.snapshot()["board"][0]["id"] == "n1"
    assert [m["name"] for m in r.public_state()["members"]] == ["c0", "c1"]


def test_broadcast_survives_a_dead_connection():
    r, sent = mk(2)

    async def boom(ev):
        raise RuntimeError("closed")

    r.members["m0"].send = boom
    asyncio.run(r.broadcast({"type": "x"}))
    assert sent == [{"type": "x"}]


def test_room_limit(monkeypatch):
    monkeypatch.setattr(R, "ROOMS", {})
    for _ in range(R.MAX_ROOMS):
        R.new_room()
    with pytest.raises(RuntimeError):
        R.new_room()


def test_microphone_is_heard_only_after_push_to_talk():
    r, _ = mk(1)
    r.grant_next()
    assert not r.mic_open("m0")  # an open microphone would also hear the room and the loudspeaker
    r.talking.add("m0")
    assert r.mic_open("m0")
    r.teacher_busy = True
    assert r.mic_open("m0")  # pressing speak stops her; the gate does not depend on her state
    r.remove("m0")
    assert not r.talking


def test_only_the_floor_holder_can_talk_in_a_group():
    r, _ = mk(2)
    r.floor = "m1"
    r.talking.update({"m0", "m1"})
    assert r.mic_open("m1") and not r.mic_open("m0")
