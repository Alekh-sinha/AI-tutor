"""Output of the script agent: spoken Hindi narration for one lesson, with board cues."""

from typing import Literal

from pydantic import BaseModel, Field


class BoardCue(BaseModel):
    """Something that appears on the board when the line starts being spoken."""

    kind: Literal["note", "svg", "image", "equation", "clear", "choice", "anim", "hide"]
    id: str | None = Field(None, description="Unique within the lesson; needed for note/svg/image/equation")
    text: str | None = Field(None, description="note: exact text to show (lesson language, short). equation: LaTeX. image: CAPTION shown under the picture (<= 4 words, e.g. 'कुल्हड़ — मिट्टी')")
    style: Literal["heading", "body", "bullet", "key"] = "body"
    options: list[str] | None = Field(None, description="choice: 3 short answer options in the lesson language")
    answer_index: int | None = Field(None, description="choice: 0-based index of the correct option")
    target: str | None = Field(None, description="anim/hide: id of a note/image/svg/choice already on the board")
    effect: Literal["pulse", "shake", "bounce", "tick", "cross", "arrow", "glow"] | None = Field(
        None, description="anim: pulse=draw the eye, shake=wrong/danger, bounce=joy, tick=correct, cross=wrong, arrow=look here, glow=important"
    )
    description: str | None = Field(
        None, description="svg/image: what to draw, precisely, with every label in the lesson language"
    )


class ScriptLine(BaseModel):
    text: str = Field(description="One or two short spoken sentences in the lesson language")
    pages: list[int] = Field(description="Textbook pages the claim in this line comes from; [] for pure transitions")
    cues: list[BoardCue] = []


class LessonScript(BaseModel):
    lesson_id: str
    title: str
    language: str
    lines: list[ScriptLine]


# ---- board rhythm: a lesson that leaves the board empty or unchanged is boring, so we check it in code ----
SEC_PER_WORD = 0.42  # measured with the Chirp voice
MAX_GAP = 9.0  # seconds without a new board item
MIN_VISUAL_EVERY = 15.0  # at least one picture or diagram per this many seconds
THINK_PAUSE = 6.0  # silence after a question card, with a countdown clock


def pause_after(lines: "list[ScriptLine]", i: int) -> float:
    """Silence after line i. Only a question CARD earns a long think pause (with the countdown clock)."""
    line = lines[i]
    if any(c.kind == "choice" for c in line.cues):
        return 1.0  # time to read the card; the think line that follows carries the long pause
    if i > 0 and any(c.kind == "choice" for c in lines[i - 1].cues) and not line.pages and len(line.text.split()) <= 6:
        return THINK_PAUSE
    return 0.8 if line.text.rstrip().endswith("?") else 0.5


# ---- one scene = one screen: nothing may scroll. Heights are in % of the screen height, board budget ~60 ----
SCREEN = 60.0
H_IMAGE_ROW, H_NOTE, H_HEADING, H_CHOICE, H_SVG = 32.0, 8.0, 11.0, 30.0, 34.0
H_IMAGE_ROW_WITH_CARD = 20.0  # pictures shrink when a question card shares the screen


def _height(items: list[str]) -> float:
    h, run = 0.0, 0
    row = H_IMAGE_ROW_WITH_CARD if "choice" in items else H_IMAGE_ROW
    for k in items:
        if k == "img":
            run += 1
            if run % 3 == 1:
                h += row
            continue
        run = 0
        h += {"note": H_NOTE, "head": H_HEADING, "choice": H_CHOICE, "svg": H_SVG}[k]
    return h


def _kind(c: "BoardCue") -> str | None:
    if c.kind == "image":
        return "img"
    if c.kind == "note":
        return "head" if c.style == "heading" else "note"
    return c.kind if c.kind in ("choice", "svg") else None


def paginate(script: "LessonScript") -> "LessonScript":
    """Make every scene fit one screen, by code (the model cannot count screen space).

    When the next item would overflow: first `hide` the OLDEST notes of earlier lines (pictures stay while they are still being
    discussed); only if no notes are left, start a new scene with `clear`. Animations aimed at removed items are dropped.
    """
    script = script.model_copy(deep=True)
    board: list[tuple[str | None, str, int]] = []  # (id, kind, line index)
    for li, line in enumerate(script.lines):
        hides: list[str] = []
        cleared = False
        for c in list(line.cues):
            if c.kind == "clear":
                board, cleared = [b for b in board if b[2] == li], True
                continue
            if c.kind == "hide":
                board = [b for b in board if b[0] != c.target]
                continue
            kind = _kind(c)
            if kind is None:
                continue
            while board and _height([k for _, k, _ in board] + [kind]) > SCREEN:
                old = next((n for n, (_, k, l) in enumerate(board) if k in ("note", "head") and l < li), None)
                if old is not None:
                    hides.append(board.pop(old)[0])
                else:
                    if not cleared:
                        line.cues.insert(0, BoardCue(kind="clear"))
                        cleared = True
                    board = [b for b in board if b[2] == li]
                    break
            board.append((c.id, kind, li))
        line.cues = [BoardCue(kind="hide", target=h) for h in hides if h] + line.cues
    # animations aimed at something that is no longer (or not yet) on the board are dropped
    on_board: set[str] = set()
    for line in script.lines:
        kept = []
        same_line = {x.id for x in line.cues if x.kind != "anim" and x.id}
        for c in line.cues:
            if c.kind == "clear":
                on_board = set()
            elif c.kind == "hide":
                on_board.discard(c.target)
            elif c.kind == "anim" and c.target not in on_board and c.target not in same_line:
                continue
            elif c.id:
                on_board.add(c.id)
            kept.append(c)
        line.cues = kept
    return script


def layout_problems(script: "LessonScript") -> list[str]:
    """Captions are required on pictures (they carry the label). Overflow is fixed by `paginate`, not reported."""
    return [
        f"line {i}: image {c.id} needs a short caption in `text` (object + material, <= 4 words)"
        for i, line in enumerate(script.lines)
        for c in line.cues
        if c.kind == "image" and not c.text
    ]


def rhythm_problems(script: "LessonScript", concepts: int = 3, min_visual_every: float = MIN_VISUAL_EVERY, max_gap: float = MAX_GAP, show_questions: bool = True) -> list[str]:
    script = paginate(script)
    problems: list[str] = []
    # `a` is time spent speaking; think pauses are excluded from gaps because the countdown clock fills them
    t, a, last_item, total_visuals, starts = 0.0, 0.0, 0.0, 0, []
    for i, line in enumerate(script.lines):
        starts.append(t)
        kinds = [c.kind for c in line.cues]
        shows = [k for k in kinds if k not in ("clear", "anim", "hide")]
        if shows:
            if a - last_item > max_gap:
                problems.append(f"line {i}: the board had no new item for {a - last_item:.0f}s before this line (max {max_gap:.0f}s)")
            last_item = a
        if "clear" in kinds and not shows:
            problems.append(f"line {i}: `clear` without a new item in the same line leaves the board blank; add the next picture or note to this same line")
        total_visuals += sum(k in ("svg", "image") for k in kinds)
        speak = len(line.text.split()) * SEC_PER_WORD
        t += speak + pause_after(script.lines, i)
        a += speak + 0.5
    if a - last_item > max_gap + 4:
        problems.append(f"the last {a - last_item:.0f}s have no new board item: show the recap points one by one")
    for i, line in enumerate(script.lines if show_questions else []):  # the director's lecture style asks rhetorical questions aloud; the card shows the real one
        if line.text.rstrip().endswith("?"):
            nearby = script.lines[max(i - 1, 0) : i + 1]
            if not any(c.kind not in ("clear", "anim", "hide") for l in nearby for c in l.cues):
                problems.append(f"line {i}: the question is not shown on the board; add a `key` note with the question (and an emoji)")
    problems += interaction_problems(script, t, concepts)
    problems += layout_problems(script)
    need = int(t // min_visual_every)
    if total_visuals < need:
        problems.append(f"only {total_visuals} pictures/diagrams in about {t:.0f}s; need at least {need}")
    return problems


ANSWER_PREFIX = "उत्तर है"  # the line that reveals a choice card's answer
ANIM_EVERY = 40.0  # at least one animation per this many seconds


def interaction_problems(script: "LessonScript", total_seconds: float, concepts: int) -> list[str]:
    """Question cards and animations must be well-formed: the assembler relies on these rules."""
    problems: list[str] = []
    ids: set[str] = set()
    choices = anims = 0
    scene_images = 0  # pictures on the board right now
    for i, line in enumerate(script.lines):
        for c in line.cues:
            if c.kind == "image":
                scene_images += 1
            if c.kind == "choice":
                choices += 1
                if scene_images == 0:
                    problems.append(f"line {i}: the question card {c.id} has no photo of its subject on the board; show it with the card (e.g. the pencil taken apart into its parts), captioned with the object's name only, never the answer")
                if not c.id or not c.text or not c.options or not (2 <= len(c.options) <= 4) or c.answer_index is None or not (0 <= c.answer_index < len(c.options)):
                    problems.append(f"line {i}: choice cue needs id, text (question), 3 options and a valid answer_index")
                nxt = script.lines[i + 1 : i + 3]
                if not (len(nxt) == 2 and not nxt[0].pages and len(nxt[0].text.split()) <= 6 and nxt[1].text.startswith(ANSWER_PREFIX)):
                    problems.append(f"line {i}: a choice card must be followed by a short think line (<= 6 words, no pages) and then a line starting '{ANSWER_PREFIX} —'")
            elif c.kind == "anim":
                anims += 1
                if not c.target or c.target not in ids | {x.id for x in line.cues if x.id}:
                    problems.append(f"line {i}: anim target {c.target!r} is not an element shown earlier or in this line")
                if not c.effect:
                    problems.append(f"line {i}: anim needs an effect")
            elif c.kind == "clear":
                ids.clear()
                scene_images = 0
            elif c.kind == "hide":
                ids.discard(c.target)
            if c.id:
                ids.add(c.id)
    if choices != concepts:
        problems.append(f"{choices} question card(s) for {concepts} concept(s): exactly one card per concept")
    need = int(total_seconds // ANIM_EVERY)
    if anims < need:
        problems.append(f"only {anims} animation(s) in about {total_seconds:.0f}s; need at least {need}")
    return problems


def scene_spans(script: "LessonScript") -> list[tuple[int, int, float]]:
    """(first line, last line, seconds of speech) of every scene, a scene being the lines between two `clear`s."""
    spans, start, secs = [], 0, 0.0
    for i, line in enumerate(script.lines):
        if i > 0 and any(c.kind == "clear" for c in line.cues):
            spans.append((start, i - 1, secs))
            start, secs = i, 0.0
        secs += len(line.text.split()) * SEC_PER_WORD + 0.5
    spans.append((start, len(script.lines) - 1, secs))
    return spans
