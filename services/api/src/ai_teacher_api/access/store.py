"""Tiny document store behind the access layer (users, credits, ledger, requests, flags).
Two backends with the same five calls: MemoryStore (tests, local development; optionally kept in a JSON file) and FirestoreStore (the deployed service).
Chosen by env STORE=memory|firestore (default memory). All calls are synchronous and thread-safe; async code calls them with asyncio.to_thread."""

import copy
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path


class MemoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, dict[str, dict]] = {}
        self._saved = 0.0
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text())
            except Exception:  # noqa: BLE001 - a damaged dev file must not stop the server
                self.data = {}

    def _save(self) -> None:
        if not self.path or time.time() - self._saved < 1.0:
            return
        self._saved = time.time()
        small = {k: v for k, v in self.data.items() if k != "ledger"}  # the ledger is large and only useful while running
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(small, ensure_ascii=False))

    def get(self, coll: str, id: str) -> dict | None:
        with self.lock:
            d = self.data.get(coll, {}).get(id)
            return copy.deepcopy(d) if d is not None else None

    def set(self, coll: str, id: str, doc: dict) -> None:
        with self.lock:
            self.data.setdefault(coll, {})[id] = copy.deepcopy(doc)
            self._save()

    def add(self, coll: str, doc: dict) -> str:
        id = uuid.uuid4().hex[:12]
        self.set(coll, id, doc)
        return id

    def add_many(self, coll: str, docs: list[dict]) -> None:
        for d in docs:
            self.add(coll, d)

    def atomic(self, coll: str, id: str, fn: Callable[[dict | None], dict]) -> dict:
        """Read-modify-write one document; concurrent callers never lose an update."""
        with self.lock:
            new = fn(copy.deepcopy(self.data.get(coll, {}).get(id)))
            self.data.setdefault(coll, {})[id] = new
            self._save()
            return copy.deepcopy(new)

    def increment(self, coll: str, id: str, deltas: dict[str, float]) -> None:
        """Add to numeric fields without reading first (`a.b` = field b inside map a). Creates missing fields."""
        with self.lock:
            doc = self.data.setdefault(coll, {}).setdefault(id, {})
            for path, delta in deltas.items():
                node = doc
                *parents, leaf = path.split(".")
                for k in parents:
                    node = node.setdefault(k, {})
                node[leaf] = node.get(leaf, 0) + delta
            self._save()

    def query(self, coll: str, where: dict | None = None, order: str | None = None, desc: bool = True, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = [dict(v, id=k) for k, v in self.data.get(coll, {}).items() if all(v.get(f) == x for f, x in (where or {}).items())]
        if order:
            rows.sort(key=lambda r: r.get(order) or 0, reverse=desc)
        return copy.deepcopy(rows[:limit])


class FirestoreStore:
    def __init__(self, project: str, prefix: str = ""):
        from google.cloud import firestore

        self.fs = firestore
        self.db = firestore.Client(project=project)
        self.prefix = prefix

    def _c(self, coll: str):
        return self.db.collection(self.prefix + coll)

    def get(self, coll, id):
        s = self._c(coll).document(id).get()
        return s.to_dict() if s.exists else None

    def set(self, coll, id, doc):
        self._c(coll).document(id).set(doc)

    def add(self, coll, doc):
        ref = self._c(coll).document()
        ref.set(doc)
        return ref.id

    def add_many(self, coll, docs):
        for i in range(0, len(docs), 400):  # one round trip per 400 documents
            batch = self.db.batch()
            for d in docs[i:i + 400]:
                batch.set(self._c(coll).document(), d)
            batch.commit()

    def atomic(self, coll, id, fn):
        ref = self._c(coll).document(id)

        @self.fs.transactional
        def run(tx):
            s = ref.get(transaction=tx)
            new = fn(s.to_dict() if s.exists else None)
            tx.set(ref, new)
            return new

        return run(self.db.transaction())

    def increment(self, coll, id, deltas):
        """Server-side atomic increments (no transaction, so a busy user's many small spends do not contend for the document)."""
        self._c(coll).document(id).update({k: self.fs.Increment(v) for k, v in deltas.items()})

    def query(self, coll, where=None, order=None, desc=True, limit=200):
        q = self._c(coll)
        for f, x in (where or {}).items():
            q = q.where(filter=self.fs.FieldFilter(f, "==", x))
        if order and not where:  # an ordered query with a filter needs a composite index; sort in memory instead
            q = q.order_by(order, direction=self.fs.Query.DESCENDING if desc else self.fs.Query.ASCENDING)
        rows = [dict(d.to_dict(), id=d.id) for d in q.limit(limit if not where else 1000).stream()]
        if order and where:
            rows.sort(key=lambda r: r.get(order) or 0, reverse=desc)
        return rows[:limit]


_store = None


def get_store():
    global _store
    if _store is None:
        if os.environ.get("STORE", "memory") == "firestore":
            from ai_teacher_api.common.settings import PROJECT

            _store = FirestoreStore(PROJECT, os.environ.get("STORE_PREFIX", ""))
        else:
            from ai_teacher_api.common.paths import DATA_DIR

            _store = MemoryStore(DATA_DIR / "app-store.json")
    return _store


def set_store(s) -> None:
    global _store
    _store = s
