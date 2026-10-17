"""Live room smoke test (needs the API on :8000 and real Vertex access). Run: cd services/api && uv run python ../../tests/e2e/live_smoke.py [lesson-id|topic]
Two children join a room; the host starts the class; checks: teacher voice arrives, captions, plan, board events, one question then silence, hand-raise -> floor -> the child's (synthesized Hindi) answer is heard and answered."""

import asyncio
import audioop
import json
import sys
import urllib.request

import websockets

import os
PORT = os.environ.get("API_PORT", "8000")
BASE, WS = f"http://localhost:{PORT}", f"ws://localhost:{PORT}"
ARG = sys.argv[1] if len(sys.argv) > 1 else "lesson-1-v2"
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, detail, flush=True)
    if not ok:
        fails.append(name)


def child_speech(text: str) -> bytes:
    from ai_teacher_api.common.tts import RATE, synth_line
    from google.cloud import texttospeech as gt

    pcm = synth_line(gt.TextToSpeechClient(), text, "Zephyr", "hi-IN", 1.0)
    return audioop.ratecv(pcm, 2, 1, RATE, 16000, None)[0]


class Client:
    def __init__(self, name, key=""):
        self.name, self.key, self.events, self.audio, self.ws = name, key, [], 0, None

    async def open(self, code):
        self.ws = await websockets.connect(f"{WS}/live/ws/{code}?name={self.name}&key={self.key}", max_size=None)
        self.task = asyncio.create_task(self.read())

    async def read(self):
        try:
            async for m in self.ws:
                if isinstance(m, bytes):
                    self.audio += len(m)
                else:
                    self.events.append(json.loads(m))
        except Exception:
            pass

    async def send(self, **ev):
        await self.ws.send(json.dumps(ev))

    def types(self):
        return [e["type"] for e in self.events]

    def caption(self):
        return "".join(e.get("delta", "") for e in self.events if e["type"] == "caption")


async def until(pred, timeout, step=0.5):
    t = 0
    while t < timeout:
        if pred():
            return True
        await asyncio.sleep(step)
        t += step
    return False


async def main():
    lesson = ARG if ARG.startswith("lesson") else ""
    req = urllib.request.Request(BASE + "/live/rooms", json.dumps({"lesson_id": lesson}).encode(), {"content-type": "application/json"})
    room = json.load(urllib.request.urlopen(req))
    host, kid = Client("गुरुजी-होस्ट", room["host_key"]), Client("रानी")
    await host.open(room["code"])
    await kid.open(room["code"])
    await asyncio.sleep(1)
    check("both joined", any(e["type"] == "state" and len(e["members"]) == 2 for e in host.events))
    await host.send(type="start", topic="" if lesson else ARG)
    check("teacher voice streams to BOTH children", await until(lambda: host.audio > 50000 and kid.audio > 50000, 150), f"{host.audio}/{kid.audio} bytes")
    check("captions arrive", await until(lambda: len(kid.caption()) > 20, 30), kid.caption()[:80])
    def spoke_and_finished():  # a caption_end AFTER some caption (a tools-only turn ends with an empty caption_end first)
        t = kid.types()
        return "caption" in t and "caption_end" in t[t.index("caption"):]

    check("teacher turn completes and the floor opens", await until(spoke_and_finished, 150))
    await asyncio.sleep(2)
    print("   teacher said:", kid.caption()[:300], flush=True)
    # hand raise -> floor
    await kid.send(type="hand")
    await host.send(type="hand")
    check("floor goes to the first hand", await until(lambda: any(e["type"] == "state" and e.get("floor") for e in kid.events[-6:]), 15))
    me = next(e["id"] for e in kid.events if e["type"] == "hello")
    holder = [e for e in kid.events if e["type"] == "state"][-1]["floor"]
    speaker = kid if holder == me else host
    n_before = kid.audio
    cap_before = len(kid.caption())
    await speaker.send(type="talk", on=True)  # push-to-talk: only now is the microphone heard
    pcm = child_speech("बिजली बल्ब में बैटरी से तार के रास्ते आती है।")
    for i in range(0, len(pcm), 3200):
        await speaker.ws.send(pcm[i:i + 3200])
        await asyncio.sleep(0.1)
    await speaker.send(type="done")
    check("the child's speech is understood (heard transcript)", await until(lambda: any(e["type"] == "heard" and e["delta"].strip() for e in kid.events), 40), "".join(e["delta"] for e in kid.events if e["type"] == "heard")[:120])
    check("teacher answers the child", await until(lambda: kid.audio > n_before + 20000 and len(kid.caption()) > cap_before + 20, 90))
    print("   teacher then said:", kid.caption()[cap_before:cap_before + 300], flush=True)
    check("plan arrives", await until(lambda: "plan" in kid.types(), 150))
    check("board gets something", await until(lambda: any(e["type"] == "board" for e in kid.events), 60))
    for c in (kid, host):
        await c.ws.close()
    print("FAILED:" if fails else "all passed", fails)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
