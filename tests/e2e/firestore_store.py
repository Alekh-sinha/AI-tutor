"""The credit logic against REAL Firestore (collections prefixed seekho_test_, deleted at the end). Run: cd services/api && uv run python ../../tests/e2e/firestore_store.py"""
import threading
import time

from ai_teacher_api.access import credits
from ai_teacher_api.access.store import FirestoreStore, get_store, set_store
from ai_teacher_api.common.settings import PROJECT

prefix = f"seekho_test_{int(time.time())}_"
set_store(FirestoreStore(PROJECT, prefix))
store = get_store()
try:
    u = credits.login("fs-a@example.com", "A")
    assert u["status"] == "pending", u
    credits.grant("fs-a@example.com", 10, by="admin")
    errs = []

    def worker():
        try:
            for _ in range(10):
                credits.spend("fs-a@example.com", 10_000, "model", "m")
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    t0 = time.time()
    [t.start() for t in ts]
    [t.join() for t in ts]
    d = credits.get("fs-a@example.com")
    print("errors:", errs, "| spent:", d["spent_micro"], "expected", 8 * 10 * 10_000, "| seconds", round(time.time() - t0, 1))
    assert not errs and d["spent_micro"] == 800_000, d
    # the deployed service batches: many spends are summed and written once; check() already counts what is waiting
    credits.enable_batching(0.2)
    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert credits.balance_micro(credits.get("fs-a@example.com")) == 10_000_000 - 1_600_000, credits.balance_micro(credits.get("fs-a@example.com"))
    time.sleep(1.5)
    d = credits.get("fs-a@example.com")
    assert d["spent_micro"] == 1_600_000 and d["day_spent"][credits.today()] == 1_600_000, d
    store.add("requests", {"email": "fs-a@example.com", "type": "credit", "status": "open", "created": time.time()})
    assert len(store.query("requests", {"status": "open"})) == 1
    n = 0
    for _ in range(20):
        n = len(store.query("ledger", {"email": "fs-a@example.com", "kind": "model"}, order="ts", limit=500))
        if n == 160:
            break
        time.sleep(1)
    assert n == 160, n
    print("FIRESTORE OK")
finally:
    for coll in ("users", "ledger", "requests"):
        for r in store.query(coll, limit=1000):
            store.db.collection(prefix + coll).document(r["id"] if "id" in r else r["email"]).delete()
