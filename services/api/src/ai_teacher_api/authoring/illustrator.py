"""Agent 1 (experiment): writes the ILLUSTRATED lesson as markdown and LOOKS at every picture it draws (ReAct loop).

The brain is a Gemini 3 text model (function calling + it can see images returned by tools). The image model is only a tool.
"""

import io
import json
import time
from pathlib import Path

from google import genai
from google.adk.agents import LlmAgent
from google.genai import types
from PIL import Image

from ai_teacher_api.safety import policy
from ai_teacher_api.common.settings import PROJECT, resolve_model

IMAGE_MODEL = "gemini-3.1-flash-image"  # setting: any image model callable at `global`
STYLE = (
    "Realistic documentary photograph, natural daylight, true-to-life colours and textures, candid and warm, shallow depth of "
    "field, in a real rural village in Bihar, India. Authentic everyday Indian clothing, objects and homes; dignified, not staged. "
    "NOT a cartoon, NOT an illustration, NOT a 3D render. ABSOLUTELY NO text, letters, numbers, logos, signs or branded packaging anywhere. " + policy.PICTURE_RULE + " Subject: "
)
MAX_IMAGE_CALLS = 30
MAX_REFERENCES = 4

_state: dict = {"dir": Path("."), "model": IMAGE_MODEL, "calls": 0, "budget": MAX_IMAGE_CALLS, "log": [], "attempts": [], "allowed": None}


def configure(directory: Path, image_model: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _state.update(dir=directory, model=image_model, calls=0, budget=MAX_IMAGE_CALLS, log=[], attempts=[], allowed=None)


def set_budget(calls: int) -> None:
    """Image calls allowed in the next agent run (a revision round gets fewer)."""
    _state.update(calls=0, budget=calls)


def set_redraw_allowed(names: set[str] | None) -> None:
    """In a revision round only these existing pictures may be redrawn (None = any). New names are always allowed."""
    _state["allowed"] = names


def _note_attempt(name: str, attempt: int, outcome: str, seconds: float, kind: str = "generate") -> None:
    """Every try is logged (printed + saved), so retries are never invisible."""
    rec = {"name": name, "kind": kind, "attempt": attempt, "outcome": outcome, "seconds": round(seconds, 1), "at": time.strftime("%H:%M:%S")}
    _state["attempts"].append(rec)
    print(f"[img-attempt] {kind} {name} #{attempt}: {outcome} ({rec['seconds']}s)", flush=True)
    with (_state["dir"] / "image-attempts.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _jpeg(img: Image.Image, size: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((size, size))
    buf = io.BytesIO()
    copy.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def generate_image(name: str, prompt: str, references: str = "") -> dict:
    """Draw ONE photograph and get it back so you can look at it.

    This image model draws STILL, simple scenes well: one or two objects close up, materials side by side, a person doing a simple thing.
    It draws badly: motion, things collapsing, breaking or pouring, exact counts, relative sizes, tiny parts (rings, screws, hinges),
    and anything that must be arranged or sorted precisely. If your idea needs those, ask for the closest still moment (for example
    "before" and "after" as two pictures) or teach that part in words instead.

    Args:
        name: short unique id for this picture, like "dadaji_kulhad" (letters, digits, underscore).
        prompt: concrete English description of the photo: who (age, clothes), where, what they hold or do, light, close-up
            or wide. Never ask for any writing in the picture.
        references: optional comma-separated names of EARLIER pictures whose people/place/objects must look the same
            (keeps characters consistent). At most 4.

    Returns:
        {"status": "ok", "name": name, "photo": the picture} or {"status": "error", "error": why}. LOOK at the photo
        and check it before you use it; call again with a better prompt if it is wrong.
    """
    if _state["calls"] >= _state["budget"]:
        return {"status": "error", "error": f"image budget of {_state['budget']} calls is used up; finish with what you have"}
    if _state["allowed"] is not None and (_state["dir"] / f"{name}.webp").exists():
        return {"status": "error", "error": f"picture {name!r} was already accepted and the reviewers did not flag it: keep it. A flagged picture is changed with edit_image, and a new picture needs a new name"}
    _state["calls"] += 1
    refs = [r.strip() for r in references.split(",") if r.strip()][:MAX_REFERENCES]
    parts: list = [types.Part(text=STYLE + prompt)]
    for r in refs:
        f = _state["dir"] / f"{r}.webp"
        if not f.exists():
            return {"status": "error", "error": f"reference picture {r!r} does not exist"}
        parts.append(types.Part.from_bytes(data=_jpeg(Image.open(f), 768, 80), mime_type="image/jpeg"))
    return _render(name, parts, "generate", refs)


def _render(name: str, parts: list, kind: str, refs: list[str]) -> dict:
    """Call the image model (with retries and a log of every attempt), save the picture as WebP, return it for the agent to look at."""
    client = genai.Client(vertexai=True, project=PROJECT, location="global")
    last, t0 = "", time.time()
    for attempt in range(1, 7):
        t_try = time.time()
        try:
            r = client.models.generate_content(
                model=_state["model"], contents=parts,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            images = [p for p in r.candidates[0].content.parts if p.inline_data and p.inline_data.mime_type.startswith("image/")]
            if not images:
                last = "the model returned no image: describe a simpler, more concrete change"
                _note_attempt(name, attempt, "no image returned", time.time() - t_try, kind)
                break
            img = Image.open(io.BytesIO(images[-1].inline_data.data)).convert("RGB")
            full = Image.new("RGB", img.size)
            full.paste(img)
            full.thumbnail((768, 768))
            full.save(_state["dir"] / f"{name}.webp", "WEBP", quality=75)
            _note_attempt(name, attempt, "ok", time.time() - t_try, kind)
            _state["log"].append({"name": name, "kind": kind, "seconds": round(time.time() - t0, 1), "attempts": attempt, "refs": refs,
                                  "returned_images": len(images)})
            return {"status": "ok", "name": name, "photo": types.Part.from_bytes(data=_jpeg(img, 512, 70), mime_type="image/jpeg")}
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
            _note_attempt(name, attempt, last, time.time() - t_try, kind)
            if not any(k in last for k in ("RESOURCE_EXHAUSTED", "429", "503", "UNAVAILABLE", "INTERNAL")):
                break
            time.sleep(20)
    _state["log"].append({"name": name, "kind": kind, "error": last})
    return {"status": "error", "error": last}


EDIT_PREFIX = (
    "Edit this photograph. Keep the scene, the people, the objects, the composition, the colours and the realistic photographic style exactly as they are. "
    "Change ONLY this: "
)
EDIT_SUFFIX = " The result must still contain no text, letters, numbers, logos or branded packaging."


def edit_image(name: str, change: str) -> dict:
    """Change an EXISTING photograph, keeping everything else in it exactly as it is, and get it back to look at.

    Args:
        name: id of an existing picture.
        change: ONE concrete change in plain English, e.g. "add a thin metal band between the pencil and the eraser",
            "fill the steel glass with clear water, visible from above", "remove all printed text from the packets".

    Returns:
        {"status": "ok", "name": name, "photo": the edited picture} or {"status": "error", "error": why}.
    """
    f = _state["dir"] / f"{name}.webp"
    if not f.exists():
        return {"status": "error", "error": f"picture {name!r} does not exist"}
    if _state["calls"] >= _state["budget"]:
        return {"status": "error", "error": f"image budget of {_state['budget']} calls is used up; finish with what you have"}
    if _state["allowed"] is not None and name not in _state["allowed"]:
        return {"status": "error", "error": f"picture {name!r} was not flagged by the reviewers, or can no longer be changed: leave the picture as it is and make the narration claim only what it clearly shows"}
    _state["calls"] += 1
    versions = _state["dir"] / "versions"
    versions.mkdir(exist_ok=True)
    (versions / f"{name}-{time.strftime('%H%M%S')}.webp").write_bytes(f.read_bytes())  # keep the picture we are about to change
    parts = [types.Part(text=EDIT_PREFIX + change + EDIT_SUFFIX), types.Part.from_bytes(data=_jpeg(Image.open(f), 768, 85), mime_type="image/jpeg")]
    return _render(name, parts, "edit", [name])


def view_picture(name: str) -> dict:
    """Look at an existing photograph.

    Args:
        name: id of an existing picture.
    """
    f = _state["dir"] / f"{name}.webp"
    if not f.exists():
        return {"status": "error", "error": f"picture {name!r} does not exist"}
    return {"status": "ok", "name": name, "photo": types.Part.from_bytes(data=_jpeg(Image.open(f), 512, 70), mime_type="image/jpeg")}


INSTRUCTION = """# Role
You are an excellent teacher preparing one lesson of a recorded video course for Class 6 children (11-12 years) in Hindi-medium schools in Bihar. Many are
first-generation learners watching alone on a phone, with nobody at home to explain. Your goal is that each child UNDERSTANDS, not just hears or memorises.

# Teaching
Take one concept at a time, and introduce a new term only when the child has enough context for it. For each concept think: what exactly must be taught
(facts, definitions, terms); what the child should be able to do afterwards; what familiar experience can be the starting point; what the child should
observe, compare or reason out; what wrong belief they are likely to hold; what question would show they understood. Then teach in the order that suits
the concept: usually a familiar experience, an observation to make, the picture that makes it visible, then the textbook term in simple Hindi with the link
to the experience made explicit, the likely misconception corrected respectfully, and one check question. Do not force a village example where another
explains better. Never leave a reasoning step for the child to guess.

# Plain text only
The lecture is read aloud and shown as plain text. No LaTeX, no $ signs, no markdown tables. Write formulas as plain Unicode (4Al + 3O₂ → 2Al₂O₃, H₂O, CO₂)
and, in the sentences the teacher speaks, say them in words ("एल्युमीनियम ऑक्सीजन से मिलकर एल्युमीनियम ऑक्साइड बनाता है") with the formula only as a short note.

# Fidelity to the book
The Plan is the authority for what the book says. Keep its facts, definitions, terms and meaning; explain hard terms in simple Hindi without replacing them
by inaccurate ones; never contradict, distort or invent textbook content. Examples, analogies, stories and demonstrations are yours, but they must be
correct, and where an analogy could mislead, say where it stops. Cover every concept and essential point of the Plan. If the Plan has a gap that stops
you teaching accurately, list it under "## Gaps" instead of inventing.

# Pictures: the blackboard of this video
In the old days a teacher wrote the concept on the blackboard. Here pictures take its place, so the child sees the idea instead of only hearing it.
A child watching on a phone loses attention fast, like in a film where nothing changes: a picture left on the screen while the teacher talks for a minute
stops being looked at. So the screen should change whenever the teacher's point changes. Each new thing you ask the child to look at, each step of an
experience, each comparison or contrast deserves its own picture, so there is always something new for their eyes to follow, and what they see is what they
remember. An experience you only narrate (water running through a cloth) is understood better when it is seen.
For each concept first decide what the child must SEE: which idea, objects, actions, differences or relationships; what would still be unclear from one picture;
whether a comparison, a close-up or a sequence would explain it better. Then get the pictures with generate_image and LOOK at each one: does it show exactly
that idea, accurately, so a Class 6 child reads it correctly? If not, draw it again. Then read your narration together with the picture as the child would;
if a step or link is missing, add a picture or say it in words. Pictures are photographs and carry no text, so definitions, labels and facts go in the
narration. Use only file names that generate_image returned.

# Hindi
Natural spoken Hindi, short sentences, familiar words, talking to the child as a teacher in class ("बच्चो, ध्यान से देखो", "अब सोचो"). Textbook terms are
used and explained. Not babyish, not formal, no unexplained English jargon. Do not assume lab equipment, internet, money or an adult's help.

# Output
A lesson is at most 10 minutes spoken, so the whole lecture is about 900-1200 words: choose the examples that teach best and keep it tight.
Write the complete lesson in Hindi as markdown: an opening that makes the child curious; then for each concept its learning aim, the teacher's spoken words
with pictures placed where the teacher points (![what the child sees and why](file_name)), the misconception, and one check question with options A, B, C,
a line "[Pause]", and the correct answer with a short explanation (no new ideas in it). The question tests the aim, ideally in a slightly different
situation, with one correct option and two tempting misconceptions. End with a short recap, and one safe home activity using household things (what to
need, do, observe, conclude)."""
INSTRUCTION += "\n\n" + policy.POLICY


def build_illustrator(model: str | None = None) -> LlmAgent:
    return LlmAgent(name="illustrator", model=resolve_model(model), instruction=INSTRUCTION, tools=[generate_image])
