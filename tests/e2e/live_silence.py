"""Live teacher must wait for the child. Solo room, topic class; the "child" says nothing, but the room's loudspeaker echo is simulated: while the teacher talks, her own voice is fed back into the
child's microphone (the bug seen on a real laptop). Needs an API (default :8000, set API_PORT) and real Vertex access. Run: cd services/api && uv run python ../../tests/e2e/live_silence.py [topic]
Checks: nothing is 'heard' (the echo is dropped server side), the first teacher turn ends at a question, and she stays silent for 25 s afterwards (no self-answer, no new captions)."""

import asyncio
import audioop
import json
import os
import re
import sys
import urllib.request

import websockets

PORT = os.environ.get("API_PORT", "8000")
BASE, WS = f"http://localhost:{PORT}", f"ws://localhost:{PORT}"
TOPIC = sys.argv[1] if len(sys.argv) > 1 else "friction"
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, detail, flush=True)
    if not ok:
        fails.append(name)


async def main():
    req = urllib.request.Request(BASE + "/live/rooms", json.dumps({"lesson_id": ""}).encode(), {"content-type": "application/json"})
    room = json.load(urllib.request.urlopen(req))
    ws = await websockets.connect(f"{WS}/live/ws/{room['code']}?name=abc&key={room['host_key']}", max_size=None)
    ev, state = [], {"audio": 0, "last_audio": 0.0}
    loop = asyncio.get_event_loop()

    async def read():
        async for m in ws:
            if isinstance(m, bytes):
                state["audio"] += len(m)
                state["last_audio"] = loop.time()
                pcm16k = audioop.ratecv(m, 2, 1, 24000, 16000, None)[0]  # the echo: what the loudspeaker plays reaches the microphone
                await ws.send(pcm16k)
            else:
                ev.append((loop.time(), json.loads(m)))

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

    def caps():
        return "".join(e["delta"] for _, e in ev if e["type"] == "caption")

    # her turns chain by themselves (preparing -> plan -> first step) until she asks a question; wait for the turn that ends with one
    def asked():
        ends = [i for i, (_, e) in enumerate(ev) if e["type"] == "caption_end"]
        return bool(ends) and "?" in "".join(e["delta"] for _, e in ev[: ends[-1]] if e["type"] == "caption")[-160:]

    await until(asked, 220)
    ends = [t for t, e in ev if e["type"] == "caption_end"]
    check("teacher spoke", state["audio"] > 100000 and len(caps()) > 40, f"{state['audio']} bytes")
    text = caps()
    print("   she said:", text[:900], flush=True)
    check("nothing was 'heard' from the echo", not any(e["type"] == "heard" and e["delta"].strip() for _, e in ev), str([e for _, e in ev if e["type"] == "heard"][:3]))
    last_end = ends[-1] if ends else 0
    await asyncio.sleep(25)
    later = [e for t, e in ev if t > last_end + 1 and e["type"] == "caption"]
    check("silent for 25 s after her turn (waiting for the child)", not later, "".join(e["delta"] for e in later)[:200])
    turn = text.split("?")[0] if "?" in text else text
    check("a question was asked", "?" in text)
    check("no self-answer after a question", not re.search(r"\?\s*(बिल्कुल|सही|शाबाश|वाह|ठीक कहा|तुमने)", text), text[-200:])
    check("pictures/board were used", any(e["type"] == "board" and e.get("op") == "add" and e["el"]["type"] == "image" for _, e in ev) or any(e["type"] == "board" for _, e in ev),
          f"{sum(1 for _, e in ev if e['type'] == 'board')} board events, {sum(1 for _, e in ev if e['type'] == 'board' and e.get('el', {}).get('type') == 'image')} images")
    task.cancel()
    await ws.close()
    print("FAILED:" if fails else "all passed", fails)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
