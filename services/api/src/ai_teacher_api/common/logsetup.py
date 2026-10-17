"""Feature logs. Every feature writes structured events (one JSON object per line) to <repo>/logs/<feature>.jsonl, so when something is wrong
the owner can say "the problem is in the director" and the evidence is in logs/director.jsonl: what each agent was asked, what checks failed, which
repairs ran, and (when asked) the agent's own explanation.

    from ai_teacher_api.common.logsetup import get
    log = get("director")
    log.info("round", n=2, problems=5)
"""

import json
import os
import threading
import time
from pathlib import Path

from ai_teacher_api.common.settings import WEB_PUBLIC

LOG_DIR = WEB_PUBLIC.parents[2] / "logs"
FEATURES = ("app", "content", "classic", "authoring", "director", "tutor", "teacher", "live")
MAX_FIELD = 6000  # characters kept per field (agent explanations can be long)
_lock = threading.Lock()


def _clip(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_FIELD else v[:MAX_FIELD] + f"...[+{len(v) - MAX_FIELD} chars]"
    if isinstance(v, dict):
        return {str(k): _clip(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clip(x) for x in v]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return _clip(str(v))


class FeatureLog:
    def __init__(self, feature: str):
        self.feature = feature
        self.path = LOG_DIR / f"{feature}.jsonl"

    def _write(self, level: str, event: str, fields: dict) -> None:
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "feature": self.feature, "level": level, "event": event, **_clip(fields)}
        line = json.dumps(rec, ensure_ascii=False)
        try:
            with _lock:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass  # logging must never break the work
        if level != "info" and not os.environ.get("K_SERVICE"):
            print(f"[{self.feature}] {level.upper()} {event} {json.dumps(_clip(fields), ensure_ascii=False)[:300]}", flush=True)
        if os.environ.get("K_SERVICE"):  # Cloud Run: the container disk is lost, so every event also goes to the platform log (searchable with textPayload:"[live]")
            print(f"[{self.feature}] {level.upper()} {event} {json.dumps(_clip(fields), ensure_ascii=False)[:700]}", flush=True)

    def info(self, event: str, **fields) -> None:
        self._write("info", event, fields)

    def warn(self, event: str, **fields) -> None:
        self._write("warn", event, fields)

    def error(self, event: str, **fields) -> None:
        self._write("error", event, fields)


_logs: dict[str, FeatureLog] = {}


def get(feature: str) -> FeatureLog:
    return _logs.setdefault(feature, FeatureLog(feature))


def tail(feature: str, n: int = 100, level: str | None = None) -> list[dict]:
    """Last n events of a feature (optionally only warn/error), newest last."""
    p = LOG_DIR / f"{feature}.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[-5000:]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if level is None or rec.get("level") == level:
            out.append(rec)
    return out[-n:]
