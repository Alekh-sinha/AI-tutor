"""Access API: sign-in, who am I, requests for access / more credit, and the admin's user dashboard.
Requests are decided by the admin once a day (after 9:00 PM IST); every message to users says so, so nobody waits anxiously."""

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ai_teacher_api.access import auth, credits, usage
from ai_teacher_api.access.store import get_store
from ai_teacher_api.common import logsetup

log = logsetup.get("app")
router = APIRouter()
REVIEW_NOTE = "Requests are reviewed every day after 9:00 PM IST. You will see the result here, and you can keep watching the free lessons meanwhile."
REVIEW_NOTE_HI = "अनुरोध रोज़ रात 9:00 बजे (IST) के बाद देखे जाते हैं। नतीजा यहीं दिखेगा, तब तक मुफ़्त पाठ देखते रहिए।"


@router.get("/auth/config")
def auth_config() -> dict:
    return {"auth_mode": auth.mode(), "google_client_id": auth.GOOGLE_CLIENT_ID, "dev_login": os.environ.get("AUTH_DEV_LOGIN") == "1", "review_note": REVIEW_NOTE, "review_note_hi": REVIEW_NOTE_HI}


class GoogleIn(BaseModel):
    credential: str = Field(max_length=4000)


@router.post("/auth/google")
def auth_google(body: GoogleIn, request: Request, response: Response) -> dict:
    claims = auth.verify_google(body.credential)
    u = credits.login(claims["email"], claims.get("name", ""), claims.get("picture", ""))
    auth.set_cookie(response, request, u["email"])
    log.info("login", email=u["email"], status=u["status"], count=u["login_count"])
    return credits.view(u)


@router.get("/auth/dev")
def auth_dev(email: str, request: Request, response: Response) -> dict:
    if os.environ.get("AUTH_DEV_LOGIN") != "1":
        raise HTTPException(404)
    u = credits.login(email, email.split("@")[0])
    auth.set_cookie(response, request, u["email"])
    return credits.view(u)


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
async def me(u: dict | None = Depends(auth.optional_user)) -> dict:
    """Anonymous visitors get {signed_in: false}. Signed-in users get balance, status and any request that is still open."""
    if u is None:
        return {"signed_in": False}
    out = {"signed_in": True, **credits.view(u), "open_requests": [{"id": r["id"], "type": r["type"], "created": r["created"]} for r in get_store().query("requests", {"email": u["email"], "status": "open"})]}
    out["review_note"], out["review_note_hi"] = REVIEW_NOTE, REVIEW_NOTE_HI
    decided = [r for st in ("approved", "rejected") for r in get_store().query("requests", {"email": u["email"], "status": st}, limit=5)]
    decided.sort(key=lambda r: r.get("decided") or 0, reverse=True)
    out["recent_decisions"] = [{"type": r["type"], "status": r["status"], "usd": round(r.get("amount_micro", 0) / credits.M, 2), "decided": r["decided"]} for r in decided[:3]]
    return out


class RequestIn(BaseModel):
    note: str = Field("", max_length=400)


def _open_request(email: str, kind: str, note: str) -> dict:
    store = get_store()
    if store.query("requests", {"email": email, "type": kind, "status": "open"}):
        return {"status": "already_open", "message": REVIEW_NOTE}
    store.add("requests", {"email": email, "type": kind, "note": note, "status": "open", "created": time.time(), "decided": None, "amount_micro": 0})
    log.info("request", email=email, kind=kind)
    return {"status": "sent", "message": REVIEW_NOTE}


@router.post("/access/request")
async def access_request(body: RequestIn, u: dict | None = Depends(auth.optional_user)) -> dict:
    if u is None:
        raise HTTPException(401, {"code": "sign_in", "message": "Please sign in first."})
    if u["status"] == "active":
        return {"status": "already_active", "message": "You already have access."}
    return _open_request(u["email"], "access", body.note)


@router.post("/credit/request")
async def credit_request(body: RequestIn, u: dict = Depends(auth.active_user)) -> dict:
    return _open_request(u["email"], "credit", body.note)


# ---------------------------------------------------------------- admin
admin = APIRouter(prefix="/admin", dependencies=[Depends(auth.admin_user)])


@admin.get("/overview")
def overview() -> dict:
    store = get_store()
    users = store.query("users", limit=2000)
    day = credits.today()
    reqs = store.query("requests", {"status": "open"})
    return {"users": len(users), "active": sum(1 for x in users if x["status"] == "active" and x["role"] != "admin"), "pending_users": sum(1 for x in users if x["status"] == "pending"),
            "open_access_requests": sum(1 for r in reqs if r["type"] == "access"), "open_credit_requests": sum(1 for r in reqs if r["type"] == "credit"),
            "spent_today_usd": round(sum(x.get("day_spent_micro", 0) for x in users if x.get("day") == day) / credits.M, 2),
            "spent_total_usd": round(sum(x.get("spent_micro", 0) for x in users) / credits.M, 2),
            "granted_total_usd": round(sum(x.get("credit_micro", 0) for x in users) / credits.M, 2),
            "logged_in_today": sum(1 for x in users if credits.time.strftime("%Y-%m-%d", credits.time.gmtime(x.get("last_login", 0) + 19800)) == day),
            "flags": len(store.query("flags", limit=500))}


@admin.get("/users")
def users() -> list[dict]:
    rows = get_store().query("users", order="last_login", limit=1000)
    return [credits.view(r) for r in rows]


@admin.get("/users/{email}")
def user_detail(email: str) -> dict:
    d = credits.get(email)
    if d is None:
        raise HTTPException(404, "unknown user")
    ledger = get_store().query("ledger", {"email": email.lower()}, order="ts", limit=100)
    return {"user": credits.view(d), "ledger": [{"ts": r["ts"], "kind": r["kind"], "model": r.get("model", ""), "usd": round(r["micro"] / credits.M, 4), "detail": r.get("detail", "")} for r in ledger],
            "requests": get_store().query("requests", {"email": email.lower()}, order="created", limit=20)}


class GrantIn(BaseModel):
    usd: float = Field(gt=0, le=1000)
    note: str = Field("", max_length=200)


@admin.post("/users/{email}/grant")
def grant(email: str, body: GrantIn, a: dict = Depends(auth.admin_user)) -> dict:
    out = credits.grant(email, body.usd, by=a["email"], note=body.note)
    log.info("grant", email=email, usd=body.usd, by=a["email"])
    return credits.view(out)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|blocked|pending)$")


@admin.post("/users/{email}/status")
def set_status(email: str, body: StatusIn) -> dict:
    if credits.get(email) is None:
        raise HTTPException(404, "unknown user")
    return credits.view(credits.set_status(email, body.status))


class CapIn(BaseModel):
    usd: float = Field(ge=0, le=1000)


@admin.post("/users/{email}/cap")
def set_cap(email: str, body: CapIn) -> dict:
    if credits.get(email) is None:
        raise HTTPException(404, "unknown user")
    return credits.view(credits.set_daily_cap(email, body.usd))


@admin.get("/requests")
def requests(status: str = "open") -> list[dict]:
    return get_store().query("requests", {"status": status}, order="created", desc=False, limit=200)


class DecideIn(BaseModel):
    approve: bool
    usd: float = Field(10.0, ge=0, le=1000)


@admin.post("/requests/{rid}/decide")
def decide(rid: str, body: DecideIn, a: dict = Depends(auth.admin_user)) -> dict:
    store = get_store()
    r = store.get("requests", rid)
    if r is None or r["status"] != "open":
        raise HTTPException(404, "request not open")
    if body.approve:
        credits.grant(r["email"], body.usd or credits.START_CREDIT_USD, by=a["email"], note=f"{r['type']} request")
    store.set("requests", rid, {**r, "status": "approved" if body.approve else "rejected", "decided": time.time(), "amount_micro": round(body.usd * credits.M) if body.approve else 0})
    log.info("request-decided", id=rid, email=r["email"], approve=body.approve, usd=body.usd)
    return {"status": "approved" if body.approve else "rejected"}


@admin.get("/flags")
def flags() -> list[dict]:
    return get_store().query("flags", order="ts", limit=200)


class PublicIn(BaseModel):
    ids: list[str] = Field(max_length=20)


@admin.get("/lessons")
def all_lessons() -> dict:
    """Every built lesson (for choosing the free ones) and the current public list."""
    import json

    from ai_teacher_api.access import library
    from ai_teacher_api.common.settings import WEB_PUBLIC

    f = WEB_PUBLIC / "lessons" / "index.json"
    return {"lessons": json.loads(f.read_text()) if f.exists() else [], "public": library.public_ids()}


@admin.post("/public-lessons")
def set_public(body: PublicIn) -> dict:
    from ai_teacher_api.access import library

    library.set_public_ids([i for i in body.ids if library.ID.match(i)])
    return {"public": library.public_ids()}
