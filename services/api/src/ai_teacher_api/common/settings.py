"""Runtime config. GCP access comes from the machine's gcloud ADC; no keys live in the repo."""

import os
from pathlib import Path as _P

from dotenv import load_dotenv

load_dotenv(_P(__file__).resolve().parents[3] / ".env")  # services/api/.env: Langfuse keys etc. (gitignored)

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "automation-ai-507911")
# Text models are served from the `global` location; TTS and image models from us-central1.
TEXT_LOCATION = "global"
MEDIA_LOCATION = "us-central1"

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", TEXT_LOCATION)

# Models the UI may offer (all verified callable in this project on 2026-10-12).
TEXT_MODELS: dict[str, str] = {
    "gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini-3.5-flash": "Gemini 3.5 Flash",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro (preview)",
    "gemini-3-flash-preview": "Gemini 3 Flash (preview)",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
}
DEFAULT_TEXT_MODEL = os.environ.get("TEXT_MODEL", "gemini-3.6-flash")


def resolve_model(model: str | None) -> str:
    model = model or DEFAULT_TEXT_MODEL
    if model not in TEXT_MODELS:
        raise ValueError(f"unknown model {model!r}; choose one of {sorted(TEXT_MODELS)}")
    return model


def retrying_model(model: str | None):
    """The model for a LIVE (child waiting) agent: the same model, but 429/503 are retried inside the call (a few seconds each) instead of ending the turn half way."""
    from google.adk.models.google_llm import Gemini
    from google.genai import types

    return Gemini(model=resolve_model(model), retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=20.0, http_status_codes=[429, 503]))


# Cloud TTS Chirp 3 HD voices offered in the UI (Hindi, hi-IN). "Zephyr" chosen by the user after listening.
VOICES: dict[str, str] = {
    "Zephyr": "Zephyr",
    "Aoede": "Aoede",
    "Leda": "Leda",
    "Charon": "Charon",
    "Puck": "Puck",
    "Orus": "Orus",
}
DEFAULT_VOICE = os.environ.get("TTS_VOICE", "Zephyr")

# On a 429 the pipeline moves down this list (flash-class only: fast and cheap). The user's chosen model goes first.
FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash"]

# where the player serves lessons, audio and images from
from pathlib import Path  # noqa: E402

WEB_PUBLIC = Path(__file__).resolve().parents[5] / "apps/web/public"

# The reviewer must be at least as strong as the author: a Flash reviewer missed flaws in Flash-written lessons (see CLAUDE.md).
LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")  # Live API (streaming voice, native audio, async tool calls); verified 2026-10-15 in this project at us-central1 (NOT global)
LIVE_LOCATION = os.environ.get("LIVE_LOCATION", "us-central1")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.1-pro-preview")
REVIEW_PASSES = int(os.environ.get("REVIEW_PASSES", "2"))  # independent reviews whose findings are combined

# the chapter folder whose briefs ("what the book says") the doubt chat uses as its authority (later: one folder per book/chapter)
CHAPTER_DIR = Path(os.environ.get("CHAPTER_DIR", str(WEB_PUBLIC.parents[2] / "data/ch6")))
