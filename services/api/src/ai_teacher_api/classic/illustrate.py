"""Illustration tool for the visual agent: Gemini image model -> compressed WebP, with NO text in the picture."""

import hashlib
import io
import time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from ai_teacher_api.common.settings import MEDIA_LOCATION, PROJECT

IMAGE_MODEL = "gemini-2.5-flash-image"
STYLE = (
    "Realistic documentary photograph, natural daylight, true-to-life colours and textures, candid and warm, shallow depth of field, "
    "shot in a real rural village in Bihar, India. Authentic everyday Indian clothing, objects and homes; dignified, not staged, "
    "not a stereotype. NOT a cartoon, NOT an illustration, NOT a painting. "
    "ABSOLUTELY NO text, letters, numbers, logos or signs anywhere in the picture. Subject: "
)

_target: dict = {"dir": Path("."), "lesson": "lesson"}


def set_image_target(directory: Path, lesson_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _target.update(dir=directory, lesson=lesson_id)


def image_path(lesson_id: str, cue_id: str, directory: Path | None = None) -> Path:
    return (directory or _target["dir"]) / f"{lesson_id}-{cue_id}.webp"


def generate_illustration(cue_id: str, scene: str) -> dict:
    """Draw a text-free illustration for an `image` cue and save it.

    Args:
        cue_id: id of the image cue this picture is for.
        scene: a concrete visual description in English: who, where, what they hold or do, colours, mood.
            Do not ask for any writing in the picture.

    Returns:
        {"ok": bool, "error": str}. If ok is false, fix the scene description and call again.
    """
    path = image_path(_target["lesson"], cue_id)
    stamp = path.with_suffix(".scene")
    digest = hashlib.sha1((STYLE + scene).encode()).hexdigest()
    if path.exists() and stamp.exists() and stamp.read_text() == digest:
        return {"ok": True, "error": ""}  # same scene as before: keep the picture, save the money
    client = genai.Client(vertexai=True, project=PROJECT, location=MEDIA_LOCATION)
    last = ""
    for attempt in range(1, 5):
        try:
            r = client.models.generate_content(model=IMAGE_MODEL, contents=STYLE + scene)
            for part in r.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                    img.thumbnail((768, 768))
                    img.save(path, "WEBP", quality=75)
                    stamp.write_text(digest)
                    return {"ok": True, "error": ""}
            last = "the model returned no image: describe a simpler, more concrete scene"
            break
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:160]
            if not any(k in last for k in ("RESOURCE_EXHAUSTED", "429", "503", "UNAVAILABLE", "INTERNAL")):
                break
            time.sleep(8 * attempt)
    return {"ok": False, "error": last}
