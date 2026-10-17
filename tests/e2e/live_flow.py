"""Live teacher FLOW with nobody pressing anything (no microphone, no 'continue', no answer): does she keep teaching, use the board, and not ask a question every two sentences?
Solo room, topic class; watches DURATION seconds after the class starts, then reads the room's lines from logs/live.jsonl. Needs an API (API_PORT) + real Vertex access.
Run: cd services/api && API_PORT=8001 uv run python ../../tests/e2e/live_flow.py [topic] [duration_s]
Reported: turns (words, audio seconds, ends with question), dead air between turns, tools used, how often the board was EMPTY, hints after unanswered questions."""
import asyncio, json, os, sys, time, urllib.request
import websockets

PORT = os.environ.get("API_PORT", "8000")
TOPIC = sys.argv[1] if len(sys.argv) > 1 else "friction"
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 300
LOG = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "live.jsonl")

async def main():
    req = urllib.request.Request(f"http://localhost:{PORT}/live/rooms", json.dumps({"lesson_id": ""}).encode(), {"content-type": "application/json"})
    room = json.load(urllib.request.urlopen(req)); code = room["code"]
    ws = await websockets.connect(f"ws://localhost:{PORT}/live/ws/{code}?name=abc&key={room['host_key']}", max_size=None)
    started = {"t": None}
    async def read():
        async for m in ws:
            if started["t"] is None and not isinstance(m, bytes):
                e = json.loads(m)
                if e.get("type") == "caption": started["t"] = time.time(); print("class started", flush=True)
    task = asyncio.create_task(read())
    await asyncio.sleep(1)
    await ws.send(json.dumps({"type": "start", "topic": TOPIC}))
    while started["t"] is None: await asyncio.sleep(1)
    await asyncio.sleep(DURATION)
    task.cancel(); await ws.close()
    rows = [json.loads(l) for l in open(LOG) if f'"room": "{code}"' in l]
    turns = [r for r in rows if r["event"] == "teacher-turn"]
    print(f"\n{len(turns)} turns in {DURATION}s")
    for r in turns:
        q = "?" in r["said"][-160:]
        print(f"  {r['ts'][11:]} words={r['words']:3d} audio={r['audio_seconds']:5.1f}s question={'Y' if q else '-'}  {r['said'][:70].strip()!r}")
    tools = [r for r in rows if r["event"] == "tool"]
    from collections import Counter
    print("tools:", dict(Counter(r["tool"] for r in tools)))
    empties = sum(1 for r in tools if "EMPTY" in r.get("board_now", ""))
    print(f"board EMPTY after {empties} of {len(tools)} tool calls")
    for ev in ("auto-continue", "no-answer-hint", "interrupted", "session-error", "tool-failed", "board-status-failed"):
        n = sum(1 for r in rows if r["event"] == ev)
        if n: print(f"{ev}: {n}")
    qs = sum(1 for r in turns if "?" in r["said"][-160:] and r["words"] > 0)
    words = [r["words"] for r in turns if r["words"] > 0]
    print(f"questions-ending turns {qs}/{len(words)}; median words per turn {sorted(words)[len(words)//2] if words else 0}")
asyncio.run(main())
