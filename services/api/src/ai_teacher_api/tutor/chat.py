"""Plain chat with the teacher, like ChatGPT: the child sends text, a voice recording or a photo and gets a text answer (and the same answer spoken, when they spoke or asked for voice).
No board and no scenes. The agent may add one or two pictures when a picture really helps (a lesson picture, or a newly drawn one); they arrive as separate `image` events.

Reuses the picture tools of `agent.py` (they need the per-turn state `agent.Turn`)."""

import base64
import re

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import retrying_model
from ai_teacher_api.tutor import agent as tutor

log = logsetup.get("tutor")
MAX_SPOKEN_CHARS = 1200

INSTRUCTION = """You are a friendly teacher answering a Class 6 child's questions (11-12 years, Hindi-medium school, rural Bihar), often alone on a phone with nobody to ask. The child may write,
speak, or send a photo (a page, an object, a drawing): look at it and answer what they ask.

Answer like a good chat assistant: directly, in the language the child used (usually simple Hindi), short (about 3-8 sentences). Plain text only: no markdown symbols (no ** or #); numbered points on separate lines are fine, starting from what they know.
Facts come from the BOOK POINTS in the message (when given) and school-level knowledge you are sure of; if you are not sure, say so honestly and suggest asking their teacher; never guess.
Use `show_lesson_picture` or `draw_picture` only when a picture truly helps (at most one or two per answer; a new picture is slow, so prefer a lesson picture).
Stay with the child's studies; kindly steer away from anything else, never ask for personal information. Never mock a wrong idea: say what is right in it, then fix it.
If it helps, end with one small question to check understanding."""


def build_chat_agent(model: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="chat",
        model=retrying_model(model),
        instruction=INSTRUCTION,
        tools=[tutor.show_lesson_picture, tutor.draw_picture],
        planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)),
    )


def spoken_chunks(text: str, limit: int = 380) -> list[str]:
    """Split an answer into sentences grouped up to `limit` characters (Cloud TTS takes short inputs); capped at MAX_SPOKEN_CHARS in all."""
    text = re.sub(r"[*_#`>]+", "", text).strip()[:MAX_SPOKEN_CHARS]
    sentences = re.split(r"(?<=[।?!.])\s+", text)
    chunks: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if chunks and len(chunks[-1]) + len(s) + 1 <= limit:
            chunks[-1] += " " + s
        else:
            while len(s) > limit:  # a very long sentence without a stop
                cut = s.rfind(" ", 0, limit) or limit
                chunks.append(s[:cut])
                s = s[cut:].strip()
            chunks.append(s)
    return chunks


async def speak(text: str, voice: str, session: str) -> str | None:
    """The answer as one MP3 (base64), or None when the voice fails (the text is still shown)."""
    from ai_teacher_api.common.tts import synth_retry, to_mp3

    try:
        pcm = b"".join([await synth_retry(tutor._tts_client(), c, voice, "hi-IN", 1.0) for c in spoken_chunks(text)])
        return base64.b64encode(to_mp3(pcm)).decode() if pcm else None
    except Exception as e:  # noqa: BLE001
        log.error("tts-failed", session=session, error=repr(e)[:200])
        return None
