"""DIAGNOSIS (not a pass/fail test): why does the live teacher's voice skip sentences when she calls tools while speaking?

Opens ONE Gemini Live session exactly like a class (same model/config/voice, the ORIGINAL design: the speaking model itself has the board tools), teaches a topic (default "friction") for a few turns,
and records everything that arrives, in arrival order:
  - every raw message: its parts (audio bytes / text / function call), transcript pieces, tool calls, turn_complete, generation_complete, interrupted, with arrival time
  - the audio, saved per PASS (a pass = what arrives between two tool calls / the end of a turn) as WAV files you can listen to, plus all.wav with a 1.5 s beep-silence at every tool call
  - for every pass: the tool calls that ended it, audio seconds, transcript words, words per audio second, how fast it arrived (burst factor)
  - an independent check of what was ACTUALLY SPOKEN: each pass's audio and the whole audio are transcribed by a text model and compared with the model's own transcript, sentence by sentence:
    a sentence that is in the transcript but not in the audio was never voiced (at API level, before any browser player could overwrite anything)
  - checks of the other suspects: the SDK's `.data` helper vs the raw inline_data parts, duplicate/odd-sized chunks, chunk timing
Output folder: logs/diagnose/<timestamp>-<mode>/  (report.json, timeline.jsonl, transcript.txt, pass-NN.wav, all.wav). Traces go to Langfuse when the keys are in services/api/.env.

Run (needs real Vertex access; ~3-4 minutes):
  cd services/api && uv run --no-sync python ../../tests/e2e/live_diagnose.py [topic] [--no-tools] [--turns N] [--tool-delay SECONDS]
Compare two runs: default (tools like the original class) vs --no-tools (the same model only talking = baseline)."""

import argparse
import asyncio
import difflib
import hashlib
import json
import re
import time
import wave
from pathlib import Path

from google import genai
from google.genai import types

from ai_teacher_api.common import tracing
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, LIVE_MODEL, PROJECT, TEXT_LOCATION

OUT_RATE = 24000
ROOT = Path(__file__).resolve().parents[2]

# The speaking model's instruction in the ORIGINAL design (before the 2026-10-15 redesign): it calls the board tools itself while talking.
ORIGINAL_PROMPT = """You are the class teacher in a LIVE VOICE CLASS for Class 6 children (11-12 years, Hindi medium, rural Bihar). Speak simple, warm, unhurried Hindi in short sentences, like a good teacher at the blackboard.
How you teach:
- At the start call `prepare_class` with the topic, then `plan` once (3-5 short steps). Then teach ONE step at a time: connect to something the children know, say 3-5 short sentences, write the key words on the board
  (`write_on_board`, at most 6 words each, about 3 notes at a time) WHILE you talk, and show a picture when one fits (`draw_picture`: one simple still photograph). Talk and board together. Do not announce the tools.
- End every step by asking the class ONE check question and then STOP and wait in silence.
- Facts come from the class notes you get from `prepare_class`."""
NO_TOOLS_PROMPT = """You are the class teacher in a LIVE VOICE CLASS for Class 6 children (11-12 years, Hindi medium, rural Bihar). Speak simple, warm, unhurried Hindi in short sentences, like a good teacher.
Teach ONE step at a time: connect to something the children know, then say 4-6 short sentences. End every step by asking the class ONE check question and then STOP."""
NOTES = ("TOPIC: friction. FACTS: friction is a force between two surfaces in contact that opposes sliding; it acts opposite to the direction of motion; rough surfaces give more friction, smooth less; "
         "oil/lubricants and wheels reduce it; shoes, brakes and tyres need it. STEPS: 1 what friction is (rolling marble stops) 2 why: roughness 3 increase/decrease 4 uses and harms.")


# ---- stub tools (answer at once, like production; --tool-delay simulates a slow tool)
DELAY = 0.0


async def prepare_class(topic: str) -> dict:
    """Prepare a class on a topic the children asked for. Call this once at the start.

    Args:
        topic: what the children want to learn.
    """
    return {"status": "ok", "class_notes": NOTES}


async def plan(steps: list[str]) -> dict:
    """Show the children the steps of the class (3-5 very short Hindi steps).

    Args:
        steps: the steps.
    """
    return {"status": "ok"}


async def write_on_board(text: str, style: str = "body") -> dict:
    """Write a short note (at most 6 words) on the board.

    Args:
        text: the words, in Hindi.
        style: heading, body or key.
    """
    return {"status": "ok"}


async def draw_picture(description: str, caption: str = "") -> dict:
    """Draw a new realistic photograph for the board. It appears later; keep teaching.

    Args:
        description: English description of one still, simple photograph.
        caption: at most 4 Hindi words.
    """
    return {"status": "started", "note": "the picture will appear by itself; keep teaching"}


TOOLS = [prepare_class, plan, write_on_board, draw_picture]


def words(text: str) -> list[str]:
    return [w for w in re.sub(r"[^\wऀ-ॿ ]+", " ", text.lower()).split() if w]


def sentences(text: str) -> list[str]:
    return [m.group().strip() for m in re.finditer(r"[^.?!।]+[.?!।]*\s*", text) if m.group().strip()]


def wav_bytes(pcm: bytes, rate: int = OUT_RATE) -> bytes:
    import io

    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def beep(seconds: float = 0.25) -> bytes:
    import math
    import struct

    n = int(OUT_RATE * seconds)
    return b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 880 * i / OUT_RATE))) for i in range(n))


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(OUT_RATE * seconds)


async def asr(client, pcm: bytes) -> str:
    """What is actually SAID in this audio (independent of the model's own transcript)."""
    r = await client.aio.models.generate_content(
        model=DEFAULT_TEXT_MODEL,
        contents=[types.Part.from_bytes(data=wav_bytes(pcm), mime_type="audio/wav"),
                  "Transcribe this Hindi speech EXACTLY, word for word, in Devanagari, including every sentence. Do not summarise, correct or skip anything. Output only the transcript."],
        config=types.GenerateContentConfig(temperature=0.0))
    return (r.text or "").strip()


def coverage(transcript: str, spoken_text: str) -> list[dict]:
    """For each sentence of the model's transcript: how much of it is found in the independently transcribed audio."""
    spoken = set(words(spoken_text))
    spoken_str = " ".join(words(spoken_text))
    out = []
    for s in sentences(transcript):
        ws = words(s)
        if not ws:
            continue
        hit = sum(1 for w in ws if w in spoken) / len(ws)
        # sequence match as a second opinion (word order)
        sm = difflib.SequenceMatcher(None, " ".join(ws), spoken_str, autojunk=False).find_longest_match(0, len(" ".join(ws)), 0, len(spoken_str)).size / max(1, len(" ".join(ws)))
        out.append({"sentence": s, "word_hit": round(hit, 2), "longest_run": round(sm, 2), "spoken": hit >= 0.6})
    return out


IDLE = 25.0  # seconds without any message = the model is waiting for us


async def _messages(session):
    """All messages of the session, across turns, as one stream."""
    while True:
        async for m in session.receive():
            yield m


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", nargs="?", default="friction")
    ap.add_argument("--no-tools", action="store_true")
    ap.add_argument("--turns", type=int, default=3, help="1 + the number of times we say go on after the model has been silent for 25 s")
    ap.add_argument("--tool-delay", type=float, default=0.0)
    ap.add_argument("--model", default=LIVE_MODEL)
    ap.add_argument("--location", default=TEXT_LOCATION)
    ap.add_argument("--nonblocking", action="store_true", help="declare the tools NON_BLOCKING and answer with scheduling SILENT")
    args = ap.parse_args()
    mode = ("no-tools" if args.no_tools else "tools") + ("-nonblocking" if args.nonblocking else "") + f"-{args.model}"
    out = ROOT / "logs" / "diagnose" / f"{time.strftime('%Y%m%d-%H%M%S')}-{mode}"
    out.mkdir(parents=True)
    lf = tracing.init()

    client = genai.Client(vertexai=True, project=PROJECT, location=args.location)
    decls = []
    for fn in TOOLS:
        d = types.FunctionDeclaration.from_callable(client=client, callable=fn)
        d.response = None
        if args.nonblocking:
            d.behavior = types.Behavior.NON_BLOCKING
        decls.append(d)
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=NO_TOOLS_PROMPT if args.no_tools else ORIGINAL_PROMPT,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr"))),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        tools=None if args.no_tools else [types.Tool(function_declarations=decls)],
    )

    t0 = time.monotonic()
    timeline: list[dict] = []   # every message, in arrival order
    events: list[dict] = []     # ordered: {"kind": audio|text|tool|turn_end, ...} used to cut passes
    raw_inline_bytes = sdk_data_bytes = 0
    chunk_hashes: dict[str, int] = {}
    odd_chunks = 0
    turns = 0

    def now() -> float:
        return round(time.monotonic() - t0, 3)

    first = (f"(Start the class now. The children want to learn: {args.topic}. Greet them in one sentence, say you are preparing, call prepare_class, plan, then teach step 1.)"
             if not args.no_tools else f"(Start the class now. The children want to learn: {args.topic}. Greet them in one sentence and teach step 1.)")
    async with client.aio.live.connect(model=args.model, config=cfg) as s:
        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=first)]), turn_complete=True)
        deadline = time.monotonic() + 420
        rounds_left = args.turns - 1  # "go on" messages we may send, each ONLY when the model has been silent for IDLE seconds (never while it may still be generating)
        it = _messages(s).__aiter__()
        while time.monotonic() < deadline:
            try:
                m = await asyncio.wait_for(it.__anext__(), IDLE)
            except asyncio.TimeoutError:
                if rounds_left <= 0:
                    break
                rounds_left -= 1
                timeline.append({"t": now(), "we_sent": "go on (model idle)"})
                await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text="(Go on with the next step.)")]), turn_complete=True)
                continue
            except StopAsyncIteration:
                break
            if True:
                rec: dict = {"t": now()}
                sc = m.server_content
                if sc and sc.model_turn and sc.model_turn.parts:
                    rec["parts"] = []
                    for p in sc.model_turn.parts:
                        if p.inline_data and isinstance(p.inline_data.data, bytes):
                            b = p.inline_data.data
                            raw_inline_bytes += len(b)
                            h = hashlib.md5(b).hexdigest()
                            chunk_hashes[h] = chunk_hashes.get(h, 0) + 1
                            odd_chunks += len(b) % 2
                            rec["parts"].append({"audio_bytes": len(b), "mime": p.inline_data.mime_type})
                            events.append({"kind": "audio", "pcm": b, "t": rec["t"]})
                        else:
                            rec["parts"].append({k: str(v)[:120] for k, v in p.model_dump(exclude_none=True).items()})
                if m.data:
                    sdk_data_bytes += len(m.data)
                if sc and sc.output_transcription and sc.output_transcription.text:
                    rec["transcript"] = sc.output_transcription.text
                    events.append({"kind": "text", "text": sc.output_transcription.text, "t": rec["t"]})
                if sc and sc.generation_complete:
                    rec["generation_complete"] = True
                if sc and sc.interrupted:
                    rec["interrupted"] = True
                if m.tool_call:
                    calls = [{"name": f.name, "args": f.args} for f in m.tool_call.function_calls]
                    rec["tool_call"] = calls
                    events.append({"kind": "tool", "calls": calls, "t": rec["t"]})
                    responses = []
                    for f in m.tool_call.function_calls:
                        fn = next(x for x in TOOLS if x.__name__ == f.name)
                        if args.tool_delay:
                            await asyncio.sleep(args.tool_delay)
                        responses.append(types.FunctionResponse(id=f.id, name=f.name, response=await fn(**(f.args or {})),
                                                                **({"scheduling": types.FunctionResponseScheduling.SILENT} if args.nonblocking else {})))
                    await s.send_tool_response(function_responses=responses)
                    rec["tool_response_sent"] = now()
                if sc and sc.turn_complete:
                    rec["turn_complete"] = True
                    events.append({"kind": "turn_end", "t": rec["t"]})
                    turns += 1
                timeline.append(rec)

    (out / "timeline.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in timeline))

    # ---- cut into passes: a pass ends at a tool call or at the end of a turn
    passes, cur = [], {"pcm": bytearray(), "text": "", "t0": None, "t1": None, "ended_by": None, "chunks": 0}
    for e in events:
        if e["kind"] in ("audio", "text"):
            cur["t0"] = e["t"] if cur["t0"] is None else cur["t0"]
            cur["t1"] = e["t"]
            if e["kind"] == "audio":
                cur["pcm"] += e["pcm"]
                cur["chunks"] += 1
            else:
                cur["text"] += e["text"]
        else:
            cur["ended_by"] = e["calls"] if e["kind"] == "tool" else "turn_complete"
            cur["end_t"] = e["t"]
            passes.append(cur)
            cur = {"pcm": bytearray(), "text": "", "t0": None, "t1": None, "ended_by": None, "chunks": 0}
    if cur["pcm"] or cur["text"]:
        passes.append(cur)

    all_pcm, markers = bytearray(), []
    for i, p in enumerate(passes, 1):
        sec = len(p["pcm"]) / 2 / OUT_RATE
        wcount = len(p["text"].split())
        wall = (p["t1"] - p["t0"]) if p["t0"] is not None else 0
        p.update(n=i, audio_s=round(sec, 1), words=wcount, words_per_audio_s=round(wcount / sec, 1) if sec else None, arrived_in_s=round(wall, 1), burst_factor=round(sec / wall, 1) if wall > 0.2 else None)
        (out / f"pass-{i:02d}.wav").write_bytes(wav_bytes(bytes(p["pcm"])))
        all_pcm += p["pcm"]
        if p["ended_by"] and p["ended_by"] != "turn_complete":
            markers.append(len(all_pcm))
            all_pcm += silence(0.6) + beep() + silence(0.6)  # you can hear where a tool call happened
        elif p["ended_by"] == "turn_complete":
            all_pcm += silence(1.5)
    (out / "all.wav").write_bytes(wav_bytes(bytes(all_pcm)))
    (out / "transcript.txt").write_text("\n\n".join(f"--- pass {p['n']} (ended by {[c['name'] for c in p['ended_by']] if isinstance(p['ended_by'], list) else p['ended_by']}) ---\n{p['text']}" for p in passes))

    # ---- what was actually spoken? (independent transcription of the audio we received)
    full_pcm = b"".join(bytes(p["pcm"]) for p in passes)
    full_text = " ".join(p["text"] for p in passes)
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)  # the text model that transcribes lives in `global`, whatever the Live location is
    spoken_all = await asr(client, full_pcm) if full_pcm else ""
    (out / "spoken-by-asr.txt").write_text(spoken_all)
    cov_all = coverage(full_text, spoken_all)
    for p in passes:
        if len(p["pcm"]) > 2 * OUT_RATE:
            p["asr"] = await asr(client, bytes(p["pcm"]))
            p["coverage"] = coverage(p["text"], p["asr"])

    # ---- where in the transcript were the tool calls? (character offsets in the whole transcript)
    offs, pos, abytes = [], 0, 0
    for e in events:
        if e["kind"] == "text":
            pos += len(e["text"])
        elif e["kind"] == "audio":
            abytes += len(e["pcm"])
        elif e["kind"] == "tool":
            offs.append({"at_char": pos, "audio_s_received_before": round(abytes / 2 / OUT_RATE, 1), "tools": [c["name"] for c in e["calls"]], "t": e["t"]})
    missing = [c for c in cov_all if not c["spoken"]]
    for c in cov_all:
        c["char"] = full_text.find(c["sentence"][:30])
    report = {
        "mode": mode, "model": args.model, "location": args.location, "topic": args.topic, "turns": turns,
        "totals": {"audio_s": round(len(full_pcm) / 2 / OUT_RATE, 1), "words": len(full_text.split()), "words_per_audio_s": round(len(full_text.split()) / max(0.1, len(full_pcm) / 2 / OUT_RATE), 1),
                   "normal_hindi_is": "about 2.5-3.5 words per audio second"},
        "tool_calls_at_char": offs,
        "passes": [{k: (v if k not in ("pcm",) else None) for k, v in p.items() if k != "pcm"} for p in passes],
        "sentences_total": len(cov_all), "sentences_not_spoken": len(missing),
        "not_spoken": [{"char": c["char"], "sentence": c["sentence"], "word_hit": c["word_hit"]} for c in missing],
        "suspects": {
            "sdk_data_helper_loses_audio": {"raw_inline_bytes": raw_inline_bytes, "sdk_data_bytes": sdk_data_bytes, "equal": raw_inline_bytes == sdk_data_bytes},
            "duplicate_chunks": sum(1 for v in chunk_hashes.values() if v > 1), "odd_sized_chunks": odd_chunks,
            "interrupted_events": sum(1 for r in timeline if r.get("interrupted")),
            "chunks_total": sum(chunk_hashes.values()),
        },
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))

    print(f"\n=== {mode}: {report['totals']}")
    print(f"sentences in the transcript: {len(cov_all)}; NOT found in the audio: {len(missing)}")
    for p in report["passes"]:
        print(f"pass {p['n']:>2}: audio {p['audio_s']:>5}s  words {p['words']:>3}  words/s {p['words_per_audio_s']}  arrived in {p['arrived_in_s']}s (x{p['burst_factor']} real time)  ended by "
              f"{[c['name'] for c in p['ended_by']] if isinstance(p['ended_by'], list) else p['ended_by']}")
        for c in p.get("coverage", []):
            if not c["spoken"]:
                print(f"          NOT SPOKEN ({c['word_hit']}): {c['sentence'][:110]}")
    print("tool calls at transcript character:", offs)
    print("suspects:", report["suspects"])
    print("files:", out)

    # ---- Langfuse: one trace, one span per pass (input = what ended it, output = the transcript, metadata = the numbers)
    if lf:
        with lf.start_as_current_observation(name=f"live-diagnose {args.topic} [{mode}]", as_type="span", input={"topic": args.topic, "mode": mode, "model": LIVE_MODEL}) as root:
            for p in report["passes"]:
                with lf.start_as_current_observation(name=f"pass-{p['n']:02d}", as_type="span", input={"ended_by": p["ended_by"]}) as sp:
                    sp.update(output=p["text"], metadata={k: p[k] for k in ("audio_s", "words", "words_per_audio_s", "arrived_in_s", "burst_factor", "chunks")}
                              | {"not_spoken": [c["sentence"] for c in p.get("coverage", []) if not c["spoken"]], "wav": str(out / f"pass-{p['n']:02d}.wav")})
            root.update(output={k: report[k] for k in ("totals", "sentences_total", "sentences_not_spoken", "suspects", "tool_calls_at_char")})
            url = lf.get_trace_url()
        lf.flush()
        print("Langfuse trace:", url)


asyncio.run(main())
