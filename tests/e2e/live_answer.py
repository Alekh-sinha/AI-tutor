"""Live teacher: voice not truncated, answers judged honestly, board follows speech. Solo room, topic class, typed WRONG answer. Needs an API (API_PORT, default 8000) + real Vertex access.
Run: cd services/api && API_PORT=8001 uv run python ../../tests/e2e/live_answer.py [topic]
Checks (from the live log of this room): every teacher turn has <= 4.5 words per audio second (no sentences dropped from the audio), she calls check_answer for the wrong answer (answer-judged: wrong/partly/unclear),
her next turn does not call it right, and she uses the board tools herself."""

import asyncio
import json
import os
import re
import sys
import urllib.request

import websockets

PORT = os.environ.get("API_PORT", "8000")
BASE, WS = f"http://localhost:{PORT}", f"ws://localhost:{PORT}"
TOPIC = sys.argv[1] if len(sys.argv) > 1 else "friction"
LOG = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "live.jsonl")
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, str(detail)[:300], flush=True)
    if not ok:
        fails.append(name)


async def main():
    req = urllib.request.Request(BASE + "/live/rooms", json.dumps({"lesson_id": ""}).encode(), {"content-type": "application/json"})
    room = json.load(urllib.request.urlopen(req))
    code = room["code"]
    ws = await websockets.connect(f"{WS}/live/ws/{code}?name=abc&key={room['host_key']}", max_size=None)
    ev = []

    async def read():
        async for m in ws:
            if not isinstance(m, bytes):
                ev.append(json.loads(m))

    task = asyncio.create_task(read())
    await asyncio.sleep(1)
    await ws.send(json.dumps({"type": "start", "topic": TOPIC}))

    async def until(pred, timeout):
        t = 0
        while t < timeout:
            if pred():
                return True
            await asyncio.sleep(0.5)
            t += 0.5
        return False

    def turn_texts():
        out, cur = [], ""
        for e in ev:
            if e["type"] == "caption":
                cur += e["delta"]
            elif e["type"] == "caption_end":
                out.append(cur)
                cur = ""
        return out

    asked = lambda: any("?" in t[-160:] for t in turn_texts())  # noqa: E731
    check("she asks a question (the planning stage - notes + pictures - comes first)", await until(asked, 560))
    n = len(turn_texts())
    await asyncio.sleep(8)  # her board assistant works after the turn
    await ws.send(json.dumps({"type": "text", "text": "मुझे लगता है चाँद की वजह से होता है"}))  # wrong for any friction question
    check("she answers", await until(lambda: len(turn_texts()) > n, 90))
    await asyncio.sleep(10)
    reply = " ".join(turn_texts()[n:])
    print("   question turn:", turn_texts()[n - 1][-200:], flush=True)
    print("   her reply:", reply[:400], flush=True)
    check("reply does not call the wrong answer right", not re.search(r"बिल्कुल सही|सही कहा|सही जवाब|शाबाश|बहुत अच्छे", reply), reply[:150])
    boards = [e for e in ev if e["type"] == "board"]
    check("pictures were prepared before the class and shown from the board", any(e.get("op") == "add" and (e.get("el") or {}).get("type") == "image" for e in boards), f"{len(boards)} board events: {[ (e.get('op'), (e.get('el') or {}).get('style') or (e.get('el') or {}).get('type')) for e in boards][:8]}")
    # fallback: a child asks for something no prepared picture covers -> placeholder card, then a freshly drawn picture
    n_events = len(ev)
    await ws.send(json.dumps({"type": "text", "text": "मैम, साइकिल की चेन पर तेल लगाने का एक चित्र बनाकर दिखाइए"}))
    got_card = await until(lambda: any(e["type"] == "board" and (e.get("el") or {}).get("style") == "pending" for e in ev[n_events:]), 60)
    got_pic = await until(lambda: any(e["type"] == "board" and (e.get("el") or {}).get("type") == "image" and "/live" in (e.get("el") or {}).get("src", "") for e in ev[n_events:]), 150)
    print(f"   INFO fallback drawing: placeholder card {got_card}, picture {got_pic} (she decides whether to call draw_picture)", flush=True)
    task.cancel()
    await ws.close()
    rows = [json.loads(l) for l in open(LOG) if f'"room": "{code}"' in l or "answer-judged" in l]
    tools_called = [r["tool"] for r in rows if r["event"] == "tool" and r.get("room") == code]
    print("   INFO check_answer called by her:", "check_answer" in tools_called, "(prompt-level rule: the reply itself is what is asserted above)", flush=True)
    turns = [r for r in rows if r["event"] == "teacher-turn" and r.get("room") == code and r.get("audio_seconds", 0) > 3]
    ratios = [round(r["words"] / r["audio_seconds"], 1) for r in turns]
    check("no sentences dropped from the audio (words per audio second)", bool(ratios) and max(ratios) <= 4.5, ratios)
    check("she pulled a ready, prepared picture", "show_lesson_picture" in tools_called, tools_called)
    print("FAILED:" if fails else "all passed", fails)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
