"""Step 4: ScriptLines -> one narration MP3 plus per-line timings (so board cues follow the voice).

Each line is synthesised separately (exact durations, easy to regenerate one line in the editor),
then joined with silences: a longer one after questions so the student can think and answer aloud.
Voice: Cloud Text-to-Speech Chirp 3 HD (chosen by ear over Gemini TTS, which sounded cartoonish).
"""

import asyncio
import sys

import lameenc
from ai_teacher_api.access import pricing, usage
from ai_teacher_api.common.plaintext import plain
from google.cloud import texttospeech as gt

from ai_teacher_api.director.script import LessonScript, pause_after
from ai_teacher_api.common.settings import DEFAULT_VOICE

RATE = 24000  # 16-bit mono PCM


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def synth_line(client: gt.TextToSpeechClient, text: str, voice: str, language: str, speaking_rate: float) -> bytes:
    usage.precheck()
    r = client.synthesize_speech(
        input=gt.SynthesisInput(text=plain(text)),
        voice=gt.VoiceSelectionParams(language_code=language, name=f"{language}-Chirp3-HD-{voice}"),
        audio_config=gt.AudioConfig(
            audio_encoding=gt.AudioEncoding.LINEAR16, sample_rate_hertz=RATE, speaking_rate=speaking_rate
        ),
    )
    usage.charge(pricing.tts_cost(len(plain(text))), "tts", f"chirp3-{voice}", f"{len(text)} chars")
    return r.audio_content[44:]  # drop the WAV header


async def synth_retry(client, text, voice, language, speaking_rate, attempts: int = 5) -> bytes:
    for n in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(synth_line, client, text, voice, language, speaking_rate)
        except Exception as e:  # noqa: BLE001
            retriable = any(k in repr(e) for k in ("ResourceExhausted", "429", "503", "ServiceUnavailable", "InternalServerError"))
            if not retriable or n == attempts:
                raise
            print(f"[retry] tts {n}/{attempts - 1}: {repr(e)[:80]}", file=sys.stderr, flush=True)
            await asyncio.sleep(10 * n)
    raise AssertionError("unreachable")


def to_mp3(pcm: bytes) -> bytes:
    enc = lameenc.Encoder()
    enc.set_bit_rate(48)
    enc.set_in_sample_rate(RATE)
    enc.set_channels(1)
    enc.set_quality(2)
    return bytes(enc.encode(pcm) + enc.flush())


async def narrate(
    script: LessonScript, voice: str = DEFAULT_VOICE, speaking_rate: float = 1.0, concurrency: int = 3
) -> tuple[bytes, list[dict]]:
    client = gt.TextToSpeechClient()
    sem = asyncio.Semaphore(concurrency)

    async def one(line):
        async with sem:
            return await synth_retry(client, line.text, voice, script.language, speaking_rate)

    pcms = await asyncio.gather(*(one(l) for l in script.lines))
    out, timings, t = bytearray(), [], 0.0
    for idx, (line, pcm) in enumerate(zip(script.lines, pcms)):
        dur = len(pcm) / 2 / RATE
        timings.append({"start": round(t, 2), "end": round(t + dur, 2), "text": line.text})
        gap = pause_after(script.lines, idx)
        out += pcm + silence(gap)
        t += dur + gap
    return to_mp3(bytes(out)), timings
