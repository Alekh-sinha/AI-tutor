import asyncio

from fastapi.testclient import TestClient

from ai_teacher_api.access import credits
from ai_teacher_api.access.store import MemoryStore, get_store, set_store
from ai_teacher_api.safety import gate, policy


def test_verdict_mapping():
    assert gate._result(gate.Verdict(decision="refuse", reason="x")).ok is False
    d = gate._result(gate.Verdict(decision="distress"))
    assert not d.ok and "1098" in d.message_hi and "1098" in d.message_en
    s = gate._result(gate.Verdict(decision="sensitive", rewrite="पौधों में प्रजनन"))
    assert s.ok and s.rewrite == "पौधों में प्रजनन"
    assert gate._result(gate.Verdict(decision="weird")).decision == "ok"  # unknown label never blocks a child by accident


def test_flag_is_stored_for_the_admin():
    set_store(MemoryStore())
    gate.flag("student", "bad words", "refuse", "explicit")
    rows = get_store().query("flags")
    assert rows and rows[0]["where"] == "student" and rows[0]["decision"] == "refuse"


def test_chat_blocks_before_the_agent(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "on")
    monkeypatch.setenv("AUTH_DEV_LOGIN", "1")
    set_store(MemoryStore())
    from ai_teacher_api import app as appmod

    async def refuse(text, where, media=None):
        return gate.Result(False, "refuse", "explicit", "", policy.REFUSE_HI, policy.REFUSE_EN)

    monkeypatch.setattr(gate, "screen", refuse)
    c = TestClient(appmod.app)
    c.get("/auth/dev", params={"email": "k@example.com"})
    credits.grant("k@example.com", 5, by="admin")
    r = c.post("/chat", json={"session_id": "abcdef123", "text": "something bad"})
    assert r.status_code == 200 and policy.REFUSE_HI in r.text and '"type": "done"' in r.text


def test_every_prompt_carries_the_policy():
    from ai_teacher_api.live import figures, prepare, prompt
    from ai_teacher_api.teacher import agent as teacher_agent
    from ai_teacher_api.tutor import agent, chat

    for text in (prompt.TEACHER, prepare.PLANNER, figures.WRITER, agent.INSTRUCTION, chat.INSTRUCTION, teacher_agent.INSTRUCTION):
        assert "CHILD-SAFETY POLICY" in text
    assert "Child-safe" in prepare.LIVE_STYLE
