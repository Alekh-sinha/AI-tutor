"""How the live class listens to a child. The speech model does NOT hear the microphone: it praised wrong and unintelligible answers ("बिल्कुल सही!") because it judged its own transcript.
Instead the server cuts the child's speech into utterances (energy-based end-of-speech detection, or the child's "done" button), transcribes each with a text model, has the answer checked by a separate
judge (judge.py) when a question is open, and gives the teacher TEXT: what the child said and the checker's verdict. Everything here is plain code except `transcribe`."""

import array
import io
import math
import wave
from collections import deque

from google import genai
from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION

log = logsetup.get("live")
RATE = 16000
CHUNK_S = 0.1
START_CHUNKS = 3  # 0.3 s of voice starts an utterance
END_SILENCE_S = 1.3  # this long a silence after speech ends it
MAX_UTTERANCE_S = 25
MIN_SPEECH_S = 0.4
MIN_THRESHOLD = 350  # RMS of 16-bit samples


def rms(pcm: bytes) -> float:
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    return math.sqrt(sum(x * x for x in a) / len(a)) if len(a) else 0.0


class Utterance:
    """Collects one child's microphone chunks and says when an utterance has ended."""

    def __init__(self) -> None:
        self.pre: deque[bytes] = deque(maxlen=5)  # half a second before the voice starts, so the first word is not clipped
        self.buf = bytearray()
        self.noise = 0.0
        self.loud = 0
        self.speech_s = 0.0
        self.silence_s = 0.0
        self.started = False

    def feed(self, chunk: bytes) -> bytes | None:
        """Returns the PCM of a finished utterance, else None."""
        level, secs = rms(chunk), len(chunk) / 2 / RATE
        thr = max(MIN_THRESHOLD, self.noise * 3)
        voiced = level > thr
        if not voiced:
            self.noise = level if self.noise == 0 else 0.95 * self.noise + 0.05 * level  # follows the room noise
        if not self.started:
            self.pre.append(chunk)
            self.loud = self.loud + 1 if voiced else 0
            if self.loud >= START_CHUNKS:
                self.started, self.buf = True, bytearray(b"".join(self.pre))
                self.speech_s, self.silence_s = self.loud * CHUNK_S, 0.0
            return None
        self.buf += chunk
        if voiced:
            self.speech_s += secs
            self.silence_s = 0.0
        else:
            self.silence_s += secs
        if self.silence_s >= END_SILENCE_S or len(self.buf) / 2 / RATE >= MAX_UTTERANCE_S:
            return self.finish()
        return None

    def finish(self) -> bytes | None:
        """The utterance so far (the child pressed done), or None if it was only noise."""
        pcm, speech = bytes(self.buf), self.speech_s
        self.__init__()
        return pcm if pcm and speech >= MIN_SPEECH_S else None


def wav(pcm: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


async def transcribe(pcm: bytes) -> str:
    """Hindi child speech -> text ("[unclear]" marks what could not be made out)."""
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    r = await client.aio.models.generate_content(
        model=DEFAULT_TEXT_MODEL,
        contents=[types.Part.from_bytes(data=wav(pcm), mime_type="audio/wav"),
                  "This is a Class 6 child speaking Hindi (maybe with a few English words) to their teacher. Write EXACTLY what the child said, in Devanagari. "
                  "Do not correct, complete or improve it. Write [unclear] for any part you cannot make out; if nothing is intelligible write only [unclear]. Output only the transcript."],
        config=types.GenerateContentConfig(temperature=0.0))
    text = (r.text or "").strip()
    log.info("transcribed", seconds=round(len(pcm) / 2 / RATE, 1), text=text[:200])
    return text
