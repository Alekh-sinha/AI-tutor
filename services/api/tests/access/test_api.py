"""End-to-end through the HTTP layer (FastAPI TestClient) with AUTH_MODE=on and the in-memory store: sign-in, access request, admin approval, credit exhaustion,
lesson visibility (public / own / other), chapter ownership."""
import json

import pytest
from fastapi.testclient import TestClient

from ai_teacher_api.access import credits, library, ownership
from ai_teacher_api.access.store import MemoryStore, set_store

ADMIN = "alekh.sinha09@gmail.com"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "on")
    monkeypatch.setenv("AUTH_DEV_LOGIN", "1")
    set_store(MemoryStore())
    from ai_teacher_api import app as appmod

    pub = tmp_path / "public"
    (pub / "lessons").mkdir(parents=True)
    (pub / "audio").mkdir()
    for name in ("lesson-1-v2", "lesson-2-v2", "u" + "0" * 8 + "-x-lesson-1-v2"):
        (pub / "lessons" / f"{name}.json").write_text(json.dumps({"id": name}))
    (pub / "lessons" / "index.json").write_text(json.dumps([{"id": n, "title": n, "status": "draft"} for n in ("lesson-1-v2", "lesson-2-v2")]))
    monkeypatch.setattr(library, "WEB_PUBLIC", pub)
    monkeypatch.setattr(library, "PUBLIC_FILE", tmp_path / "public-lessons.json")
    (tmp_path / "public-lessons.json").write_text(json.dumps(["lesson-1-v2"]))
    return appmod.app


def client(app, email=None):
    c = TestClient(app)
    if email:
        assert c.get("/auth/dev", params={"email": email}).status_code == 200
    return c


def test_anonymous_sees_only_the_public_lesson_and_cannot_use_the_ai(env):
    c = client(env)
    assert c.get("/me").json() == {"signed_in": False}
    r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 401
    from fastapi import FastAPI

    root = FastAPI()
    root.include_router(library.router)
    lib = TestClient(root)
    assert [e["id"] for e in lib.get("/lessons/index.json").json()] == ["lesson-1-v2"]
    assert lib.get("/lessons/lesson-1-v2.json").status_code == 200
    assert lib.get("/lessons/lesson-2-v2.json").status_code == 401  # not public


def test_new_user_waits_for_approval_then_gets_credit(env):
    c = client(env, "kid@example.com")
    me = c.get("/me").json()
    assert me["status"] == "pending" and me["balance_usd"] == 0
    assert [x["type"] for x in me["open_requests"]] == ["access"]  # the request was sent automatically at sign-in
    assert me["contact_email"] == "alekh.sinha09@gmail.com"
    r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_approved"
    assert "9:00 PM IST" in r.json()["detail"]["message"]
    sent = c.post("/access/request", json={"note": "I am a teacher"}).json()
    assert sent["status"] == "already_open" and "9:00 PM IST" in sent["message"]
    assert c.post("/access/request", json={}).json()["status"] == "already_open"  # no duplicate
    # not an admin: cannot see the dashboard
    assert c.get("/admin/overview").status_code in (403, 401)

    a = client(env, ADMIN)
    reqs = a.get("/admin/requests").json()
    assert len(reqs) == 1 and reqs[0]["email"] == "kid@example.com"
    assert a.post(f"/admin/requests/{reqs[0]['id']}/decide", json={"approve": True, "usd": 10}).json()["status"] == "approved"
    me = c.get("/me").json()
    assert me["status"] == "active" and me["balance_usd"] == 10.0 and not me["open_requests"]
    ov = a.get("/admin/overview").json()
    assert ov["active"] == 1 and ov["granted_total_usd"] == 10.0


def test_credit_runs_out_then_user_requests_more(env):
    c = client(env, "t@example.com")
    credits.grant("t@example.com", 1.0, by="admin")
    credits.spend("t@example.com", 1_000_000, "model", "m")
    r = c.post("/credit/request", json={"note": "please"})
    assert r.status_code == 200 and r.json()["status"] == "sent"
    try:
        credits.check("t@example.com")
        raise AssertionError("should be exhausted")
    except credits.CreditExhausted as e:
        assert "9:00 PM IST" in str(e)
    a = client(env, ADMIN)
    rid = a.get("/admin/requests").json()[0]["id"]
    a.post(f"/admin/requests/{rid}/decide", json={"approve": False})
    assert c.get("/me").json()["balance_usd"] == 0.0  # rejected: nothing added
    c.post("/credit/request", json={})
    rid = a.get("/admin/requests").json()[0]["id"]
    a.post(f"/admin/requests/{rid}/decide", json={"approve": True, "usd": 5})
    assert c.get("/me").json()["balance_usd"] == 5.0


def test_admin_user_table_and_block(env):
    client(env, "u1@example.com")
    a = client(env, ADMIN)
    rows = a.get("/admin/users").json()
    assert {r["email"] for r in rows} >= {"u1@example.com", ADMIN}
    detail = a.get("/admin/users/u1@example.com").json()
    assert detail["user"]["login_count"] == 1
    a.post("/admin/users/u1@example.com/grant", json={"usd": 10})
    a.post("/admin/users/u1@example.com/status", json={"status": "blocked"})
    u = client(env, "u1@example.com")
    r = u.post("/chat", json={"message": "hi"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "blocked"


def test_chapter_ownership(env):
    mine, other = "a@example.com", "b@example.com"
    assert ownership.can_access(ownership.prefix_for(mine) + "x", mine)
    assert not ownership.can_access(ownership.prefix_for(mine) + "x", other)
    assert not ownership.can_access("ch6", mine)  # the admin's chapter
    assert ownership.can_access("ch6", ADMIN)
    assert ownership.chapter_of_lesson_id("u12345678-ch2-lesson-1-v2-draft") == "u12345678-ch2"
    assert ownership.chapter_of_lesson_id("lesson-1-v2") == "ch6"


def test_forged_cookie_is_rejected(env):
    c = TestClient(env)
    c.cookies.set("ss_session", "e30=.deadbeef")
    assert c.get("/me").json() == {"signed_in": False}
