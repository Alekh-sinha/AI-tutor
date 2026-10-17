"""API smoke test (needs the API on :8000; uses text models and one TTS call per spoken sentence). Run: cd services/api && uv run python ../../tests/e2e/api_smoke.py [lesson-id]"""

import json
import sys
import urllib.request

BASE = "http://localhost:8000"
LESSON = sys.argv[1] if len(sys.argv) > 1 else "lesson-1-v2"
fails = []


def get(path, headers=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + path, headers=headers or {}), timeout=60).read())


def post_stream(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"content-type": "application/json"})
    events = []
    for line in urllib.request.urlopen(req, timeout=300):
        line = line.decode()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, detail)
    if not ok:
        fails.append(name)


check("health", get("/health") == {"status": "ok"})
check("teacher chapters", any(c["lessons"] for c in get("/teacher/chapters")))
ev = post_stream("/chat", {"session_id": "smoke-chat-1", "lesson_id": LESSON, "mode": "chat", "t": 60, "text": "मैम, कुल्हड़ मिट्टी का क्यों होता है?", "voice_reply": True})
kinds = [e["type"] for e in ev]
check("chat: text answer with voice, ends", "text" in kinds and kinds[-1] == "done" and [e for e in ev if e["type"] == "text"][0]["audio"], str(sorted(set(kinds))))
ev = post_stream("/chat", {"session_id": "smoke-chat-2", "mode": "chat", "text": "बादल कैसे बनते हैं?"})
check("chat without a lesson answers", any(e["type"] == "text" for e in ev))
ev = post_stream("/chat", {"session_id": "smoke-topic-1", "mode": "teach", "text": "मुझे बिजली का सर्किट सीखना है"})
says = [e for e in ev if e["type"] == "say"]
check("live class on the child's own topic: prepares, plans, teaches, asks and stops", "plan" in [e["type"] for e in ev] and says and says[-1]["text"].rstrip().endswith(("?", "？")) and sum(s["text"].rstrip().endswith("?") for s in says) == 1, f"{len(says)} says")
ev = post_stream("/chat", {"session_id": "smoke-live-1", "lesson_id": LESSON, "mode": "teach", "text": "कक्षा शुरू कीजिए"})
check("live: plans then teaches one step", "plan" in [e["type"] for e in ev] and "say" in [e["type"] for e in ev])
check("live: stops after asking the child", ev and [e for e in ev if e["type"] == "say"][-1]["text"].rstrip().endswith(("?", "।", ".", "!")))
logs = get("/debug/logs/tutor?n=5")
check("tutor feature log has turns", any(r["event"] == "turn" for r in logs))
print("FAILED:" if fails else "all passed", fails)
sys.exit(1 if fails else 0)
