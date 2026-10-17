"""Review nodes. Code can count items and screen space, but only a reader can tell whether the board matches the voice.

1. `review_script`  (text only, cheap): for every spoken line, what is on the board while it is said, and does it match?
2. `review_pictures` (one or two contact sheets, cheap): does each photo really show its caption, and is it a clean realistic photo?
Both return issues in plain words that go straight back to the writer / the picture generator.
"""

import io
import re
from ai_teacher_api.safety import policy
from ai_teacher_api.common.plaintext import has_latex
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from ai_teacher_api.common.lesson import Lesson
from ai_teacher_api.director.script import LessonScript, paginate
from ai_teacher_api.common.settings import resolve_model

FONT = Path(__file__).resolve().parents[3] / "assets/fonts/NotoSansDevanagari-Regular.ttf"


class Issue(BaseModel):
    where: str = Field(description="line number (script review) or image cue id (picture review)")
    problem: str
    fix: str = Field(description="the concrete change: e.g. 'move image i4 to line 9', 'caption should be X'")


class Report(BaseModel):
    issues: list[Issue]


# ------------------------------------------------------------------ 1. script review (text)
def storyboard_text(script: LessonScript) -> str:
    """Per line: what the student hears, what newly appears, and everything visible while it is said."""
    script = paginate(script)
    board: list[str] = []
    out = []
    for i, line in enumerate(script.lines):
        new = []
        for c in line.cues:
            if c.kind == "clear":
                board = []
                new.append("CLEAR (the board is wiped)")
                continue
            if c.kind == "hide":
                board = [b for b in board if not b.startswith(f"{c.target} ")]
                new.append(f"note {c.target} fades out (the rest stays)")
                continue
            if c.kind == "anim":
                new.append(f"animation {c.effect} on {c.target}")
                continue
            desc = {
                "image": f"photo {c.id} caption '{c.text}' ({c.description})",
                "note": f"note {c.id}: '{c.text}'",
                "choice": f"question card {c.id}: '{c.text}' options {c.options}",
                "svg": f"diagram {c.id} ({c.description})",
                "equation": f"equation {c.id}",
            }[c.kind]
            new.append("NEW " + desc)
            board.append(f"{c.id} " + (f"'{c.text}'" if c.text else ""))
        out.append(f"LINE {i}: \"{line.text}\"\n   " + ("\n   ".join(new) or "(nothing new)") + f"\n   VISIBLE NOW: {board}")
    return "\n".join(out)


SCRIPT_REVIEW = """You are the quality reviewer of a recorded classroom lesson for village children. A STORYBOARD lists, line by line,
what the teacher SAYS, what NEWLY appears on the board while that line is spoken, and what is VISIBLE. Find REAL mismatches only:
1. A picture or note appears BEFORE its subject is mentioned, or AFTER the teacher has moved on (e.g. a photo of wood appears while the
   teacher is still talking about the clay cup, glass and paper cup).
2. A CLEAR wipes something the teacher is still talking about in the next line or two.
3. What is visible contradicts what is said (caption/material/number wrong).
4. A concept is spoken but nothing on the board supports it, for 3 or more lines, while a picture for it is shown somewhere else.
5. A question card shown without a photo of its subject, or whose photo caption already gives away the answer.
6. A question card whose options or answer do not match the spoken question, or whose answer line says something different.
Each item should show up in the line where its subject is spoken, or at most one line earlier. Be strict about 1-3, lenient about style.
For every issue give the line number, the problem and the exact fix (usually: move cue X to line N, or delete it). If everything is
consistent return an empty list."""


def build_script_reviewer(model: str | None = None) -> LlmAgent:
    return LlmAgent(name="script_reviewer", model=resolve_model(model), instruction=SCRIPT_REVIEW, output_schema=Report, output_key="report")


async def _ask(agent: LlmAgent, parts: list[types.Part]) -> Report:
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=parts)):
        pass
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return Report.model_validate(session.state["report"])


async def review_script(script: LessonScript, model: str | None) -> list[str]:
    report = await _ask(build_script_reviewer(model), [types.Part(text=storyboard_text(script))])
    return [f"[review] line {i.where}: {i.problem}. Fix: {i.fix}" for i in report.issues]


# ------------------------------------------------------------------ 2. picture review (contact sheets)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


_EMOJI = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]")


def _text(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: str, size: int) -> None:
    """Hindi needs the Devanagari font, Latin letters/digits the default one. Draw whole RUNS (letters must shape together)."""
    x, y = xy
    fonts = {"hi": _font(size), "lat": ImageFont.load_default(size)}
    runs: list[list[str]] = []
    for ch in _EMOJI.sub("", text):
        kind = "lat" if ch.isascii() and ch.isalnum() else "hi"
        if runs and (runs[-1][0] == kind or (not ch.isalnum() and ch.isascii())):
            runs[-1][1] += ch
        else:
            runs.append([kind, ch])
    for kind, run in runs:
        d.text((x, y), run, fill=fill, font=fonts[kind])
        x += d.textlength(run, font=fonts[kind])


def scenes(lesson: Lesson) -> list[dict]:
    """Split the timeline at every `clear`: each scene = pictures + notes + the narration spoken during it."""
    out, cur = [], None
    for e in lesson.events:
        if e.type == "clear" or cur is None:
            cur = {"t": e.t, "images": [], "notes": [], "cards": []}
            out.append(cur)
        if e.type == "image":
            cur["images"].append((e.id, e.src, e.caption or ""))
        elif e.type == "note":
            cur["notes"].append(e.text)
        elif e.type == "choice":
            cur["cards"].append(e.question)
    for a, b in zip(out, out[1:] + [{"t": lesson.duration}]):
        a["end"] = b["t"]
        a["say"] = [n.text for n in lesson.narration if n.start >= a["t"] - 0.3 and n.start < b["t"] - 0.3]
    return out


def contact_sheets(lesson: Lesson, public: Path, per_sheet: int = 4) -> list[bytes]:
    """The collage: one panel per scene (photos with captions, notes, spoken words), a few panels per PNG sheet."""
    panels = []
    for k, sc in enumerate(scenes(lesson)):
        w, h = 1200, 420
        p = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(p)
        _text(d, (8, 4), f"scene {k + 1}  {sc['t']:.0f}-{sc['end']:.0f}s", "#888", 18)
        x = 8
        for cid, src, cap in sc["images"][:4]:
            f = public / src.lstrip("/")
            if f.exists():
                im = Image.open(f).convert("RGB").resize((240, 240))
                p.paste(im, (x, 30))
                _text(d, (x, 274), f"{cid}: {cap}", "black", 20)
                x += 252
        y = 30
        for n in sc["notes"][:5] + [f"[card] {q}" for q in sc["cards"]]:
            _text(d, (x + 10, y), n[:40], "#b03a00", 20)
            y += 28
        _text(d, (8, 310), " ".join(sc["say"])[:230], "#222", 18)
        panels.append(p)
    sheets = []
    for i in range(0, len(panels), per_sheet):
        group = panels[i : i + per_sheet]
        sheet = Image.new("RGB", (1200, 420 * len(group)), "white")
        for j, p in enumerate(group):
            sheet.paste(p, (0, 420 * j))
        buf = io.BytesIO()
        sheet.save(buf, "PNG")
        sheets.append(buf.getvalue())
    return sheets


PICTURE_REVIEW = """You review the photographs of a recorded lesson for village children, shown on contact sheets: each panel is one
scene (photos with their id and caption, the notes shown, and the words the teacher says meanwhile). Report only REAL problems:
- the photo does not show what its caption says (wrong object, wrong material, wrong number of things);
- the photo shows nudity, anything sexual, gore or violence, or a weapon (always report: write "unsafe" in the problem);
- the photo shows readable or gibberish text, a logo, or a sign;
- the photo looks cartoonish, deformed (hands, faces), or unrealistic;
- the photo does not fit what the teacher is saying in that scene.
`where` = the photo id (like i4). `fix` = what the new photo should show (concrete, English). Empty list if all are fine."""


async def review_pictures(lesson: Lesson, public: Path, model: str | None) -> list[Issue]:
    agent = LlmAgent(name="picture_reviewer", model=resolve_model(model), instruction=PICTURE_REVIEW, output_schema=Report, output_key="report")
    parts = [types.Part.from_bytes(data=s, mime_type="image/png") for s in contact_sheets(lesson, public)]
    return (await _ask(agent, parts + [types.Part(text="Review these contact sheets.")])).issues


# ------------------------------------------------------------------ 3. review of the ILLUSTRATED lecture (Agent 1 output)
IMG_REF = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
MIN_TOTAL_WORDS = 650  # about 5 minutes spoken, whole lecture without picture lines
MAX_TOTAL_WORDS = 1250  # a lesson is at most 10 minutes including pauses (about 0.42 s per word with the voice), and the player/schema reject more


def lecture_images(md: str) -> list[tuple[str, str]]:
    """(description, picture name) for every inline picture, in order; a trailing .webp/.png is ignored."""
    return [(d, re.sub(r"\.(webp|png|jpe?g)$", "", n.split("/")[-1])) for d, n in IMG_REF.findall(md)]


def lecture_gaps(md: str) -> str:
    m = re.search(r"^#+\s*Gaps\s*$(.*?)(?=^#+\s|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


MAX_WORDS_WITHOUT_PICTURE = 200  # about a minute and a half of speech (includes a check question, which Agent 2 shows as a card)


def attention_gaps(md: str) -> list[str]:
    """Counted in code, not judged by a model: narration between two consecutive pictures (or before the first) with nothing new on screen."""
    out, prev, pos = [], "the start of the lesson", 0
    body = re.split(r"^#+\s*(?:Recap|रिकैप|सारांश|Home activity)", md, maxsplit=1, flags=re.M | re.I)[0]
    marks = list(IMG_REF.finditer(body)) + [None]
    for m in marks:
        seg = body[pos : m.start()] if m else ""
        n = len(seg.split())
        name = re.sub(r"\.(webp|png|jpe?g)$", "", m.group(2).split("/")[-1]) if m else ""
        if m and n > MAX_WORDS_WITHOUT_PICTURE:
            out.append(f"[check] {n} words of narration between {prev} and picture {name} with nothing new on screen (limit {MAX_WORDS_WITHOUT_PICTURE}): "
                       "add ONE simple still photograph (an object, a material, a step) where the teacher's point changes, or split the passage; avoid pictures that need motion")
        if m:
            prev, pos = f"picture {name}", m.end()
    return out


def lecture_checks(md: str, img_dir: Path, concepts_expected: int) -> list[str]:
    """Plain-code checks an LLM critic would only guess at."""
    issues = []
    imgs = lecture_images(md)
    missing = sorted({n for _, n in imgs if not (img_dir / f"{n}.webp").exists()})
    if missing:
        issues.append(f"[check] these pictures are placed in the lecture but were never drawn (no file): {missing}. Draw them or remove the references")
    used = {n for _, n in imgs}
    unused = sorted(p.stem for p in img_dir.glob("*.webp") if p.stem not in used)
    if unused:
        issues.append(f"[check] these pictures were drawn but are not used in the lecture: {unused}. Place each where the teacher's point matches it (add the picture reference), or leave it out only if it does not fit any point")
    if len(imgs) < concepts_expected:
        issues.append(f"[check] only {len(imgs)} picture(s) for {concepts_expected} concepts: every concept needs at least one picture that carries its idea")
    pauses = len(re.findall(r"\[\s*Pause", md))
    options_a = len(re.findall(r"^\s*[-*]?\s*[(*]*A[)*.:]", md, re.M))  # A. / A) / (A) / **A.** / (**A**)
    if pauses != concepts_expected or options_a != concepts_expected:
        issues.append(f"[check] found {options_a} check question(s) and {pauses} [Pause] line(s) for {concepts_expected} concepts: exactly one question with options A, B, C and a [Pause] line before its answer, per concept")
    if has_latex(md):
        issues.append("[check] the lecture contains LaTeX markup ($...$, \\text{}, \\rightarrow): write formulas as plain Unicode text, e.g. 4Al + 3O₂ → 2Al₂O₃ (the voice would read the markup aloud)")
    issues += attention_gaps(md)
    words = len(IMG_REF.sub("", md).split())
    if words > MAX_TOTAL_WORDS:
        issues.append(f"[check] the lecture has about {words} words; a lesson must be at most {MAX_TOTAL_WORDS} (10 minutes spoken): cut the least essential examples and repetition, keep every concept, question and the recap")
    if words < MIN_TOTAL_WORDS:
        issues.append(f"[check] the lecture has about {words} words; a 5-minute lesson needs at least {MIN_TOTAL_WORDS}: teach each concept more fully")
    return issues


def picture_parts(img_dir: Path, images: list[tuple[str, str]], size: int = 640) -> list[types.Part]:
    """Every picture on its own at 640 px, labelled with its id and the description the lecture gives it (small contact-sheet tiles caused false findings)."""
    parts, seen = [], set()
    for desc, name in images:
        f = img_dir / f"{name}.webp"
        if name in seen or not f.exists():
            continue
        seen.add(name)
        im = Image.open(f).convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        parts.append(types.Part(text=f"PICTURE {name} (description in the lesson: {desc})"))
        parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
    return parts


LECTURE_CRITIC = """You are a strict reviewer of an ILLUSTRATED LESSON (markdown plus a sheet of its photographs, each shown with its id and the description the
author gave it) for a recorded video course for Class 6 children in Hindi-medium schools in Bihar. The LESSON PLAN below says what the book says; it is the authority.
Report only REAL, specific problems. Check:
1. Every concept and essential point of the Plan is covered. Nothing contradicts, distorts or invents textbook content. Examples are factually correct and consistent
   with the book; an analogy that could mislead says where it stops.
2. Each concept starts from a familiar experience or observation before the abstract idea; the book's term comes after; the narration links picture and concept; no
   essential reasoning step is left for the child to guess; one relevant misconception is corrected respectfully.
3. Each picture serves a clear teaching purpose and shows what its description says (right objects, materials, counts, actions); it is a realistic photograph, not a
   cartoon or 3D render; no readable text or logo; natural hands and faces; looks like rural Bihar; a person who recurs looks the same. A concept that needs more than one
   view has more than one picture. Judge pictures ONLY in the `pictures` audit (not in `issues`), and only from what is clearly visible: describe literally what you see
   first, then compare. Do not flag a detail you cannot clearly see; when unsure, it matches.
4. The subject of each check question is shown by one of the lesson's pictures (a question about sugar needs a picture with sugar in it). Exactly one check question per concept: options A, B, C; exactly one defensibly correct answer, and the answer given matches it; two plausible distractors based on
   likely misconceptions, none mixing two reasons; it tests the concept's aim, preferably in a slightly different situation; a [Pause] line precedes the answer; the
   explanation introduces no new idea.
5. Hindi is natural, simple, age-appropriate and not babyish; textbook terms are used and explained; no unexplained English jargon; one form of address (आप or तुम) is used
   consistently; no typos.
6. ATTENTION: the screen should change when the teacher's point changes. Long stretches without a picture are counted by code, so do not report them. Do report any
   experience, observation or comparison that the narration asks the child to look at or imagine and that is essential to understand the concept but has no picture.
7. SAFETY (always report): no sexual or romantic content, nudity, graphic violence, weapons, drugs or demeaning content; body and reproduction topics, if any, are textbook-level and use symbolic diagrams. The recap adds no new material. The home activity is safe, needs only ordinary household things, no purchase, internet or adult, and states what to need, do, observe
   and conclude, and reinforces an objective.
For every issue: where = "concept N", "opening", "recap", "home activity" or a picture id; problem = what is wrong; fix = the concrete change (for a photo: what the new
photo must show). If the lesson is good return an empty list. Do not invent problems."""


class ConceptAudit(BaseModel):
    concept: str
    taught: list[str] = Field(description="ideas and terms actually taught so far (this concept and earlier ones)")
    options: list[str] = Field(description="one line per option: 'A: defensible or not, and why', solving the question as a child who learned only this lesson")
    defensible_count: int
    untaught: list[str] = Field(description="ideas, terms or facts used in the question, options or the answer's explanation that the lesson never taught")
    mixed_reason_options: list[str]
    uncovered_plan_points: list[str]


class PictureAudit(BaseModel):
    id: str
    seen: str = Field(description="literal description of what is clearly visible: objects, materials, colours, number of items, people. Written BEFORE judging")
    matches: bool = Field(description="True unless something the description or narration depends on is clearly absent or wrong, or the photo has readable text/brands, deformed hands, or looks like a cartoon")
    problem: str = Field(default="", description="only when matches is False: what is clearly wrong")
    fix: str = Field(default="", description="only when matches is False: what the picture must show instead, or what the narration should say less about")


class AuditReport(BaseModel):
    audits: list[ConceptAudit]
    pictures: list[PictureAudit] = Field(description="one entry per picture id")
    other_problems: list[str] = Field(description="opening, recap, home activity, Hindi register problems")
    issues: list[Issue] = Field(description="every NON-picture violation found in the audits (text, questions, coverage, Hindi, activity), with the concrete fix")


REVIEW_METHOD = """

HOW TO REVIEW: do not skim. Work concept by concept and fill the audit for EACH concept completely BEFORE you write the issues list. Solve each check question yourself,
option by option, as a child who has learned only what this lesson taught so far, and count how many options are defensible. Look for any idea, term or fact used in a question,
an option or an explanation that the lesson never taught. Look at each picture and say what you actually see, literally, before judging it. Then turn every non-picture violation into an issue."""


async def critique_lecture(md: str, plan_text: str, img_dir: Path, model: str | None, log_to: Path | None = None) -> tuple[list[str], list[PictureAudit]]:
    """One review pass: a per-concept audit and a per-picture audit (the reasoning), then the text issues. Callers run several passes and combine them."""
    agent = LlmAgent(name="lecture_critic", model=resolve_model(model), instruction=LECTURE_CRITIC + REVIEW_METHOD, output_schema=AuditReport, output_key="report")
    parts = [types.Part(text=f"LESSON PLAN:\n{plan_text}\n\nLESSON (markdown):\n{md}\n\nTHE PICTURES, one by one:")]
    parts += picture_parts(img_dir, lecture_images(md))
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=parts)):
        pass
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    rep = AuditReport.model_validate(session.state["report"])
    if log_to is not None:
        log_to.write_text(rep.model_dump_json(indent=1, ensure_ascii=False))
    return [f"[critic] {i.where}: {i.problem}. Fix: {i.fix}" for i in rep.issues], [p for p in rep.pictures if not p.matches]
