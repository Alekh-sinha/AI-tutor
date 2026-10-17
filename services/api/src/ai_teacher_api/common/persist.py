"""Durable copy of the working files. The service works on local disk (the pipeline writes plenty of files and we did not touch that), but a Cloud Run instance's disk
disappears on every restart or deploy. So the files are MIRRORED to a Cloud Storage bucket: restore everything at start, push changes every 30 s, push once more on shutdown
and after every finished job. Single-instance design (see docs/DEPLOY.md). Switched on by env DATA_BUCKET; without it nothing happens (local development)."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_teacher_api.common import logsetup

log = logsetup.get("app")
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}
SKIP_SUFFIX = (".tmp", ".pyc")
SETTLE_SECONDS = 2.0  # a file changed within this window may still be being written: next round


class GcsBackend:
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def list(self) -> dict[str, int]:
        return {b.name: b.size for b in self.bucket.list_blobs()}

    def put(self, key: str, path: Path) -> None:
        self.bucket.blob(key).upload_from_filename(str(path))

    def get(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.bucket.blob(key).download_to_filename(str(path))

    def delete(self, key: str) -> None:
        self.bucket.blob(key).delete()


class DirBackend:
    """A folder standing in for the bucket (tests, and trying the persistence locally)."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def list(self) -> dict[str, int]:
        return {p.relative_to(self.root).as_posix(): p.stat().st_size for p in self.root.rglob("*") if p.is_file()}

    def put(self, key: str, path: Path) -> None:
        t = self.root / key
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(path.read_bytes())

    def get(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((self.root / key).read_bytes())

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


class Mirror:
    def __init__(self, backend, roots: list[tuple[Path, str]]):
        self.backend = backend
        self.roots = roots  # (local folder, key prefix)
        self.known: dict[str, tuple[int, int]] = {}  # key -> (mtime_ns, size) as last restored / pushed
        self.restored = False
        self.lock = threading.Lock()

    def _local_files(self):
        for root, prefix in self.roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.is_file() and not (SKIP_DIRS & set(p.parts)) and not p.name.endswith(SKIP_SUFFIX):
                    yield f"{prefix}/{p.relative_to(root).as_posix()}", p

    def _path(self, key: str) -> Path | None:
        for root, prefix in self.roots:
            if key.startswith(prefix + "/"):
                return root / key[len(prefix) + 1:]
        return None

    def restore(self) -> int:
        """Download every object that is missing or different locally. Sets `restored` only when all of them arrived (pushes never delete before that)."""
        remote = self.backend.list()
        todo = []
        for key, size in remote.items():
            p = self._path(key)
            if p is None:
                continue
            if not p.exists() or p.stat().st_size != size:
                todo.append((key, p))
            else:
                self.known[key] = (p.stat().st_mtime_ns, size)

        def fetch(kp):
            self.backend.get(*kp)
            st = kp[1].stat()
            self.known[kp[0]] = (st.st_mtime_ns, st.st_size)

        with ThreadPoolExecutor(8) as ex:
            list(ex.map(fetch, todo))
        self.restored = True
        log.info("persist-restore", objects=len(remote), downloaded=len(todo))
        return len(todo)

    def push(self) -> dict:
        """Upload new / changed files and delete the objects whose local file is gone."""
        with self.lock:
            now = time.time()
            up, seen = [], set()
            for key, p in self._local_files():
                seen.add(key)
                st = p.stat()
                if now - st.st_mtime < SETTLE_SECONDS:
                    continue
                if self.known.get(key) != (st.st_mtime_ns, st.st_size):
                    up.append((key, p, (st.st_mtime_ns, st.st_size)))
            for key, p, sig in up:
                self.backend.put(key, p)
                self.known[key] = sig
            gone = [k for k in list(self.known) if k not in seen] if self.restored else []
            for k in gone:
                self.backend.delete(k)
                self.known.pop(k, None)
            if up or gone:
                log.info("persist-push", uploaded=len(up), deleted=len(gone))
            return {"uploaded": len(up), "deleted": len(gone)}


_mirror: Mirror | None = None
_stop = threading.Event()


def configure(backend=None) -> Mirror | None:
    """Build the mirror from env (DATA_BUCKET) or an explicit backend (tests). Returns None when persistence is off."""
    global _mirror
    from ai_teacher_api.common.paths import DATA_DIR
    from ai_teacher_api.common.settings import WEB_PUBLIC

    if backend is None:
        bucket = os.environ.get("DATA_BUCKET")
        if not bucket:
            return None
        backend = GcsBackend(bucket)
    _mirror = Mirror(backend, [(DATA_DIR, "data")] + [(WEB_PUBLIC / s, f"public/{s}") for s in ("lessons", "audio", "img", "chat")])
    return _mirror


def start(interval: float = 30.0) -> None:
    m = _mirror
    if m is None:
        return
    m.restore()

    def loop():
        while not _stop.wait(interval):
            try:
                m.push()
            except Exception as e:  # noqa: BLE001 - a failed round is retried next time
                log.error("persist-push-failed", error=repr(e)[:300])

    threading.Thread(target=loop, daemon=True, name="persist").start()


def sync_now() -> None:
    if _mirror and _mirror.restored:
        try:
            _mirror.push()
        except Exception as e:  # noqa: BLE001
            log.error("persist-push-failed", error=repr(e)[:300])


def stop() -> None:
    _stop.set()
    sync_now()
