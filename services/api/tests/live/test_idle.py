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
    r.talk_started = now
    assert session.idle_action(r, _state(now, 30), now) is None
    r.talking.clear()
    st = _state(now, 30)
    st["pending_tools"] = 1
    assert session.idle_action(r, st, now) is None
    r.finished = True
    assert session.idle_action(r, _state(now, 30), now) is None


def test_a_lost_release_or_a_cut_off_turn_does_not_stall_the_class():
    """Regression 2026-10-17: after a child's doubt she stayed silent until the host pressed आगे बढ़िए (busy flag / speak flag never cleared)."""
    r, now = _room(), time.time()
    r.talking.add("a")
    r.talk_started = now - session.STALE_TALK - 1
    assert session.idle_action(r, _state(now, 30), now) == "continue"
    assert not r.talking
    r.teacher_busy = True
    assert session.idle_action(r, _state(now, 3), now) is None  # she may still be thinking
    assert session.idle_action(r, _state(now, session.STALE_BUSY + 1), now) == "continue"


def test_markup_and_check_only_patterns():
    from ai_teacher_api.live import session
    assert session.MARKUP.sub("", "ठीक है।</td>") == "ठीक है।"
    assert session.MARKUP.sub("", "x<no speech>{pause}\n") == "x\n"
    assert session.CHECK_ONLY.search("क्या यह समझ आया?") and not session.CHECK_ONLY.search("कौन सा बल रोकता है?")
