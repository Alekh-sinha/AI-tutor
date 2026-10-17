import time

from ai_teacher_api.live import session
from ai_teacher_api.live.room import Member, Room


def _room():
    r = Room(code="1", host_key="k")
    r.live, r.started = object(), True
    r.add(Member(id="a", name="a", send=None, send_bytes=None, is_host=True))
    return r


def _state(now, quiet):
    return {"pending_tools": 0, "last_msg": now - quiet, "play_end": 0.0}


def test_continue_after_a_short_quiet_when_no_question_is_open():
    r, now = _room(), time.time()
    assert session.idle_action(r, _state(now, 0.3), now) is None
    assert session.idle_action(r, _state(now, 1.0), now) == "continue"


def test_open_question_waits_then_hints_once():
    r, now = _room(), time.time()
    r.open_question = {"q": "?", "expected": "", "hinted": False}
    assert session.idle_action(r, _state(now, 5), now) is None
    assert session.idle_action(r, _state(now, session.QUESTION_WAIT + 1), now) == "hint"


def test_after_the_hint_the_class_goes_on_not_stalls():
    """Regression 2026-10-16: the question stayed open after the hint and the watcher never fired again (4 minutes of silence)."""
    r, now = _room(), time.time()
    r.open_question = None  # the watcher closes it when it sends the hint
    assert session.idle_action(r, _state(now, 2), now) == "continue"


def test_never_while_a_child_talks_a_tool_runs_or_the_class_is_finished():
    r, now = _room(), time.time()
    r.talking.add("a")
    assert session.idle_action(r, _state(now, 30), now) is None
    r.talking.clear()
    st = _state(now, 30)
    st["pending_tools"] = 1
    assert session.idle_action(r, st, now) is None
    r.finished = True
    assert session.idle_action(r, _state(now, 30), now) is None
