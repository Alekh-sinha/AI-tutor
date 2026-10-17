"""Users, credit balances and the spend ledger. Money is kept in micro-dollars (int). A spend is one atomic update of the user's document, so two users (or two jobs of
one user) at the same moment never lose or double-count a charge. Rules: admin = unlimited; an `active` user may spend while credit is left and today's cap (IST day) is not reached."""

import os
import threading
import time

from ai_teacher_api.access import pricing
from ai_teacher_api.access.store import get_store

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "alekh.sinha09@gmail.com").split(",") if e.strip()}
START_CREDIT_USD = float(os.environ.get("START_CREDIT_USD", "10"))
DAILY_CAP_USD = float(os.environ.get("DAILY_CAP_USD", "5"))
M = pricing.M


class AccessDenied(Exception):
    """Base of every 'you cannot use the AI right now' reason. `code` is stable for the UI; the texts are shown to the user."""

    code = "denied"
    http = 403
    en = "You cannot use this right now."
    hi = "अभी आप इसका उपयोग नहीं कर सकते।"

    def __init__(self, detail: str = ""):
        super().__init__(detail or self.en)


class NotApproved(AccessDenied):
    code, http = "not_approved", 403
    en = "Your access request is waiting. Requests are reviewed every day after 9:00 PM IST. You can still watch the free lessons."
    hi = "आपका अनुरोध प्रतीक्षा में है। अनुरोध रोज़ रात 9:00 बजे (IST) के बाद देखे जाते हैं। तब तक मुफ़्त पाठ देख सकते हैं।"


class Blocked(AccessDenied):
    code, http = "blocked", 403
    en = "This account has been paused. Please contact the admin."
    hi = "यह खाता रोक दिया गया है। कृपया एडमिन से संपर्क करें।"


class CreditExhausted(AccessDenied):
    code, http = "credit_exhausted", 402
    en = "Your credit is used up. You can ask for more credit; requests are reviewed every day after 9:00 PM IST. The free lessons stay available."
    hi = "आपका क्रेडिट ख़त्म हो गया है। आप और क्रेडिट माँग सकते हैं; अनुरोध रोज़ रात 9:00 बजे (IST) के बाद देखे जाते हैं। मुफ़्त पाठ देखते रहिए।"


class DailyCapReached(AccessDenied):
    code, http = "daily_cap", 429
    en = "You have reached today's limit. It resets at midnight IST, so please come back tomorrow."
    hi = "आज की सीमा पूरी हो गई। यह आधी रात (IST) को फिर शुरू होगी, कल आइए।"


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 19800))  # IST


def is_admin(email: str) -> bool:
    return email.lower() in ADMIN_EMAILS


def _new(email: str, name: str = "", picture: str = "") -> dict:
    admin = is_admin(email)
    return {"email": email, "name": name, "picture": picture, "role": "admin" if admin else "user", "status": "active" if admin else "pending",
            "credit_micro": 0, "spent_micro": 0, "day_spent": {}, "daily_cap_micro": round(DAILY_CAP_USD * M),
            "created": time.time(), "last_login": time.time(), "login_count": 0, "counters": {}}


def login(email: str, name: str = "", picture: str = "") -> dict:
    """Create the user on first sign-in (status pending: free lessons only until the admin approves) and note the login."""
    email = email.lower()

    def fn(d):
        d = d or _new(email, name, picture)
        d.update(name=name or d.get("name", ""), picture=picture or d.get("picture", ""), last_login=time.time(), login_count=d.get("login_count", 0) + 1)
        if is_admin(email):
            d.update(role="admin", status="active")
        return d

    return get_store().atomic("users", email, fn)


def get(email: str) -> dict | None:
    return get_store().get("users", email.lower())


def _day_spent(d: dict) -> int:
    return int((d.get("day_spent") or {}).get(today(), 0)) + _pending_total(d["email"])[0]


def balance_micro(d: dict) -> int:
    return d.get("credit_micro", 0) - d.get("spent_micro", 0) - _pending_total(d["email"])[0]


def view(d: dict) -> dict:
    """The user as the browser sees it (dollars, not micro-dollars)."""
    day_spent = _day_spent(d)
    return {"email": d["email"], "name": d.get("name", ""), "picture": d.get("picture", ""), "role": d["role"], "status": d["status"],
            "balance_usd": round(balance_micro(d) / M, 2), "credit_usd": round(d.get("credit_micro", 0) / M, 2), "spent_usd": round(d.get("spent_micro", 0) / M, 2),
            "today_usd": round(day_spent / M, 2), "daily_cap_usd": round(d.get("daily_cap_micro", 0) / M, 2), "unlimited": d["role"] == "admin",
            "last_login": d.get("last_login"), "login_count": d.get("login_count", 0), "counters": d.get("counters", {}), "created": d.get("created")}


def check(email: str) -> None:
    """Raise the reason when this user may not start (or continue) paid work."""
    d = get(email)
    if d is None:
        raise NotApproved()
    if d["role"] == "admin":
        return
    if d["status"] == "blocked":
        raise Blocked()
    if d["status"] != "active":
        raise NotApproved()
    if balance_micro(d) <= 0:
        raise CreditExhausted()
    if _day_spent(d) >= d.get("daily_cap_micro", 0):
        raise DailyCapReached()


# ---- spends are written as atomic increments; with batching on (the deployed service) they are first summed in memory and written once a second per user,
# so a lesson build with many parallel model calls does not hammer one database document. check() counts what is still waiting to be written.
_pending: dict[str, dict] = {}
_plock = threading.Lock()
_batching = False


_inflight: dict[str, int] = {}  # popped from _pending, being written right now (still counted by check())


def _pending_total(email: str) -> tuple[int, int]:
    p = _pending.get(email)
    return ((p["micro"] if p else 0) + _inflight.get(email, 0), 0)


def spend(email: str, micro: int, kind: str, model: str = "", detail: str = "", counter: str = "", counter_n: int = 0) -> dict | None:
    """Charge `micro` to the user and write a ledger line. Unknown users (command line runs) are not charged."""
    if micro <= 0 and not counter:
        return None
    email = email.lower()
    line = {"email": email, "ts": time.time(), "kind": kind, "model": model, "micro": micro, "detail": detail[:200]} if micro > 0 else None
    if _batching:
        with _plock:
            p = _pending.setdefault(email, {"micro": 0, "counters": {}, "lines": []})
            p["micro"] += micro
            if counter:
                p["counters"][counter] = p["counters"].get(counter, 0) + counter_n
            if line:
                p["lines"].append(line)
        return None
    return _write(email, micro, {counter: counter_n} if counter else {}, [line] if line else [])


def _write(email: str, micro: int, counters: dict, lines: list) -> dict | None:
    store = get_store()
    if store.get("users", email) is None:
        return None
    deltas = {"spent_micro": micro, f"day_spent.{today()}": micro}
    deltas.update({f"counters.{k}": v for k, v in counters.items()})
    store.increment("users", email, deltas)
    if lines:
        store.add_many("ledger", lines)
    return store.get("users", email)


def flush() -> None:
    """Write everything that is waiting (called once a second by the flusher and on shutdown)."""
    with _plock:
        batch = dict(_pending)
        _pending.clear()
        for email, p in batch.items():
            _inflight[email] = _inflight.get(email, 0) + p["micro"]
    for email, p in batch.items():
        try:
            _write(email, p["micro"], p["counters"], p["lines"])
            with _plock:
                _inflight[email] = _inflight.get(email, 0) - p["micro"]
        except Exception:
            with _plock:
                _inflight[email] = _inflight.get(email, 0) - p["micro"]  # noqa: BLE001 - put it back, the next round writes it
            with _plock:
                q = _pending.setdefault(email, {"micro": 0, "counters": {}, "lines": []})
                q["micro"] += p["micro"]
                q["lines"] += p["lines"]
                for k, v in p["counters"].items():
                    q["counters"][k] = q["counters"].get(k, 0) + v
            raise


def enable_batching(interval: float = 1.0) -> None:
    global _batching
    _batching = True

    def loop():
        while True:
            time.sleep(interval)
            try:
                flush()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=loop, daemon=True, name="credit-flush").start()


def grant(email: str, usd: float, by: str, note: str = "") -> dict:
    email = email.lower()

    def fn(d):
        d = d or _new(email)
        d["credit_micro"] = d.get("credit_micro", 0) + round(usd * M)
        if d["status"] == "pending" and d["role"] != "admin":
            d["status"] = "active"
        return d

    out = get_store().atomic("users", email, fn)
    get_store().add("ledger", {"email": email, "ts": time.time(), "kind": "grant", "model": "", "micro": -round(usd * M), "detail": f"by {by} {note}"[:200]})
    return out


def set_status(email: str, status: str) -> dict:
    return get_store().atomic("users", email.lower(), lambda d: {**d, "status": status})


def set_daily_cap(email: str, usd: float) -> dict:
    return get_store().atomic("users", email.lower(), lambda d: {**d, "daily_cap_micro": round(usd * M)})
