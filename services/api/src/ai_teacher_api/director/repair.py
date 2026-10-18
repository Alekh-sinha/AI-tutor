"""Deterministic repairs of the director's script. The director (an LLM) was asked to satisfy structure rules and kept leaving loose ends
(board gaps up to 28 s, a question card without its think line, whole concepts on one scene), so the structure is now enforced in CODE after every
director round; the model only has to supply meaning (captions, notes, animations, where ideas change).

Order: split long lines -> question-card structure -> one scene per picture group -> question scene (clear + recalled picture) -> fill board gaps with notes.
Every repair is logged to logs/director.jsonl with what it changed.
"""

import re

from ai_teacher_api.common.plaintext import has_latex, plain
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.director.script import ANSWER_PREFIX, SEC_PER_WORD, BoardCue, LessonScript, ScriptLine, scene_spans

log = logsetup.get("director")
MAX_LINE_WORDS = 26  # a longer spoken line is split at sentence ends (cues stay with the first part, a question card with the last)
THINK_LINE = "सोचिए..."
SENT = re.compile(r"(?<=[।\.\?!])\s+")


# ---------------------------------------------------------------- 0. restore narration the director dropped
WORD = re.compile(r"[\u0900-\u097F\w]{2,}")
OPTION = re.compile(r"^\s*[-*]?\s*[(*]*[ABC][)*.:]")
IMG = re.compile(r"!\[.*?\]\(.*?\)")


def lecture_sentences(md: str) -> list[str]:
    """The lecture's spoken sentences in order (markdown, headings, pictures, option lines and [Pause] removed)."""
    lines = md.splitlines()
    question_lines: set[int] = set()
    for k, ln in enumerate(lines):  # the paragraph right before an option list is the question stem (the card line reads it)
        if OPTION.match(ln):
            j = k - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            while j >= 0 and lines[j].strip() and not lines[j].lstrip().startswith("#") and not OPTION.match(lines[j]):
                question_lines.add(j)
                j -= 1
    out, in_question, in_activity = [], False, False
    for idx, raw in enumerate(lines):
        t = raw.strip()
        plain = re.sub(r"[*_`]+", "", t).lstrip("-• ").strip()
        if re.match(r"^\[\s*Pause", t):
            in_question = False  # what follows is the answer and its explanation: spoken
            continue
        if re.match(r"^(जाँच प्रश्न|जांच प्रश्न|प्रश्न|सवाल|Check Question|Question)", plain):
            in_question = True  # the question and its options are read by the card line, not restored
        if t.startswith("#"):
            in_activity = bool(re.search(r"(गृह\s*कार्य|घर पर|Home\s*activity|होमवर्क)", t, re.I))  # the activity is shown as a panel at the end, not narrated in full
        if in_activity:
            continue
        if not t or t.startswith("#") or t == "---" or IMG.search(t) or OPTION.match(t) or in_question or idx in question_lines or re.match(r"^(सीखने का उद्देश्य|हमारा लक्ष्य|Learning aim)", plain):
            continue
        out += [x.strip() for x in SENT.split(plain) if len(WORD.findall(x)) >= 3]
    return out


def _after_card_block(script: LessonScript, after: int) -> int:
    """Never insert inside a question block (card line, think line, answer line): move the insertion point behind it."""
    for c, line in enumerate(script.lines):
        if any(k.kind == "choice" for k in line.cues) and c <= after <= c + 1:
            return c + 2 if c + 2 < len(script.lines) else len(script.lines) - 1
    return after


def restore_missing(md: str, script: LessonScript, min_overlap: float = 0.5) -> list[str]:
    """The director may smooth and split the narration but the lecture IS the lesson: any lecture sentence whose words are not found in the script is inserted back,
    verbatim, after the line that covers the sentence before it. Returns the restored sentences (logged)."""
    own = [set(WORD.findall(l.text.lower())) for l in script.lines]
    line_tokens = [own[i] | (own[i + 1] if i + 1 < len(own) else set()) | (own[i + 2] if i + 2 < len(own) else set()) for i in range(len(own))]  # a smoothed line may merge neighbours
    anchor, missing = -1, []  # missing: (insert after line, sentence)
    for sent in lecture_sentences(md):
        toks = set(WORD.findall(sent.lower()))
        best, best_i = 0.0, anchor
        for i in range(max(anchor, 0), len(script.lines)):
            ov = len(toks & line_tokens[i]) / max(1, len(toks))
            if ov > best:
                best, best_i = ov, i
        if best < min_overlap:  # not after the anchor: it may still be said earlier (the director moved things); then it is NOT missing, and inserting it again would say it twice
            best_any = max((len(toks & lt) / max(1, len(toks)) for lt in line_tokens), default=0.0)
            if best_any >= min_overlap:
                continue
        if best >= min_overlap:
            anchor = best_i
        else:
            missing.append((anchor, sent))
    order = sorted(enumerate(missing), key=lambda x: (-x[1][0], -x[0]))  # from the end, and later sentences first, so earlier indices stay valid and order is kept
    for _, (after, sent) in order:
        script.lines.insert(_after_card_block(script, after) + 1, ScriptLine(text=sent, pages=[], cues=[]))
    return [s for _, s in missing]


# ---------------------------------------------------------------- 1. split long lines
def _chunks(text: str) -> list[str]:
    parts, cur = [], ""
    for sent in SENT.split(text.strip()):
        if cur and len((cur + " " + sent).split()) > MAX_LINE_WORDS:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    out = []
    for p in parts:  # a single very long sentence: break at a comma / dash near the middle
        words = p.split()
        if len(words) > MAX_LINE_WORDS + 10:
            cut = next((i for i in range(len(words) // 2, len(words)) if words[i - 1].endswith((",", "—", "–", ";"))), len(words) // 2)
            out += [" ".join(words[:cut]), " ".join(words[cut:])]
        else:
            out.append(p)
    return out


def split_long_lines(script: LessonScript) -> int:
    new, n = [], 0
    for line in script.lines:
        parts = _chunks(line.text)
        if len(parts) <= 1 or line.text.startswith(ANSWER_PREFIX) and False:
            new.append(line)
            continue
        n += len(parts) - 1
        card = [c for c in line.cues if c.kind == "choice"]
        first = [c for c in line.cues if c.kind != "choice"]
        for i, p in enumerate(parts):
            cues = (first if i == 0 else []) + (card if i == len(parts) - 1 else [])
            new.append(ScriptLine(text=p, pages=line.pages, cues=cues))
    script.lines = new
    return n


# ---------------------------------------------------------------- 2. question-card structure
def repair_cards(script: LessonScript) -> int:
    """card line -> short think line -> a line starting 'उत्तर है —' (the player's countdown and the reveal depend on it)."""
    fixes, i = 0, 0
    while i < len(script.lines):
        if any(c.kind == "choice" for c in script.lines[i].cues):
            nxt = script.lines[i + 1] if i + 1 < len(script.lines) else None
            if nxt is None or nxt.pages or len(nxt.text.split()) > 6 or nxt.text.startswith(ANSWER_PREFIX):
                script.lines.insert(i + 1, ScriptLine(text=THINK_LINE, pages=[], cues=[]))
                fixes += 1
            ans = script.lines[i + 2] if i + 2 < len(script.lines) else None
            if ans is not None and not ans.text.startswith(ANSWER_PREFIX):
                ans.text = f"{ANSWER_PREFIX} — {ans.text.lstrip('उत्तर: -—')}"
                fixes += 1
        i += 1
    return fixes


# ---------------------------------------------------------------- 3 + 4. scenes
def _base(pid: str | None) -> str:
    return (pid or "").split("~")[0]


def _find_image(script: LessonScript, base_id: str) -> BoardCue | None:
    return next((c for l in script.lines for c in l.cues if c.kind == "image" and _base(c.id) == base_id), None)


def split_long_scenes(script: LessonScript, max_sec: float) -> int:
    """A scene longer than `max_sec` is cut where a new item (preferably a picture) appears about 35 s into it, so every scene stays one idea."""
    added = 0
    for _ in range(12):
        spans = [sp for sp in scene_spans(script) if sp[2] > max_sec]
        if not spans:
            break
        a, b, _sec = spans[0]
        t, cands = 0.0, []
        for i in range(a, b + 1):
            line = script.lines[i]
            if i > a and t >= 20 and any(c.kind in ("image", "note") for c in line.cues) and not any(c.kind == "choice" for c in line.cues):
                cands.append((i, t, any(c.kind == "image" for c in line.cues)))
            t += len(line.text.split()) * SEC_PER_WORD + 0.5
        if not cands:
            break
        i = min(cands, key=lambda c: (abs(c[1] - 35) - (8 if c[2] else 0)))[0]
        script.lines[i].cues.insert(0, BoardCue(kind="clear"))
        added += 1
    return added


def scene_breaks(script: LessonScript) -> int:
    """A scene is one idea: a picture group (pictures on the same or adjacent lines) with its notes. A picture that is not part of the current group starts a new scene.
    The question card gets its own scene: clear + the picture of its subject shown again (same file, id `name~q`) + the card."""
    added = 0
    last_img_line, has_img, last_img = -10, False, None
    for i, line in enumerate(script.lines):
        kinds = [c.kind for c in line.cues]
        if "clear" in kinds:
            has_img, last_img_line = False, -10
        imgs = [c for c in line.cues if c.kind == "image"]
        if imgs and has_img and i - last_img_line > 1 and "clear" not in kinds:
            line.cues.insert(0, BoardCue(kind="clear"))
            added += 1
        if imgs:
            has_img, last_img_line, last_img = True, i, imgs[-1]
        if "choice" in kinds:
            recall = None
            card_cue = next(c for c in line.cues if c.kind == "choice")
            wanted = _find_image(script, _base(card_cue.target)) if card_cue.target else None  # the director names the picture that shows the question's subject
            pick = wanted or last_img
            if not imgs and pick is not None:
                recall = BoardCue(kind="image", id=f"{_base(pick.id)}~q", text=pick.text, description=pick.description)
            if "clear" not in [c.kind for c in line.cues] and (recall or imgs):
                line.cues.insert(0, BoardCue(kind="clear"))
                added += 1
            if recall is not None:
                at = next(k for k, c in enumerate(line.cues) if c.kind != "clear")
                line.cues.insert(at, recall)
                added += 1
            has_img, last_img_line = True, i
    return added


# ---------------------------------------------------------------- 5. fill board gaps
def gap_points(script: LessonScript, max_gap: float) -> list[int]:
    """Lines (without a new board item) at which a note must appear so that no stretch of speech exceeds `max_gap` seconds without a new item."""
    points, a, last = [], 0.0, 0.0
    for i, line in enumerate(script.lines):
        speak = len(line.text.split()) * SEC_PER_WORD + 0.5
        if any(c.kind not in ("clear", "anim", "hide") for c in line.cues):
            last = a
        elif a - last + speak > max_gap:
            points.append(i)
            last = a
        a += speak
    return points


class _Notes(BaseModel):
    notes: list[str]


async def _write_notes(texts: list[str], model: str) -> list[str]:
    agent = LlmAgent(name="board_writer", model=model, output_schema=_Notes, output_key="n", instruction=(
        "You write blackboard notes for a Hindi school lesson. For each numbered spoken line, write ONE short note (at most 6 words, Hindi, an emoji only if it helps) "
        "that the teacher would write on the board for that line: the key term, fact or step it says. Return exactly one note per line, in order."))
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    s = await sessions.create_session(app_name="ai-teacher", user_id="dev")
    msg = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    async for _ in runner.run_async(user_id="dev", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
        pass
    s = await sessions.get_session(app_name="ai-teacher", user_id="dev", session_id=s.id)
    return _Notes.model_validate(s.state["n"]).notes


async def fill_gaps(script: LessonScript, max_gap: float, model: str) -> int:
    total = 0
    for attempt in range(3):
        pts = gap_points(script, max_gap)
        if not pts:
            break
        texts = [script.lines[i].text for i in pts]
        try:
            notes, _ = await with_model_fallback(lambda m: _write_notes(texts, m), model)
            if len(notes) != len(pts):
                raise ValueError(f"{len(notes)} notes for {len(pts)} gaps")
        except Exception as e:  # noqa: BLE001
            log.warn("gap-notes-fallback", error=repr(e)[:200], gaps=len(pts))
            notes = [" ".join(t.split()[:5]) for t in texts]  # worse text, but the gap is closed
        used = {c.id for l in script.lines for c in l.cues if c.id}
        for i, note in zip(pts, notes):
            nid = f"g{i}_{attempt}"
            while nid in used:
                nid += "x"
            script.lines[i].cues.append(BoardCue(kind="note", id=nid, text=note.strip()[:60], style="bullet"))
        total += len(pts)
    return total


def fix_blank_clears(script: LessonScript) -> int:
    """A `clear` in a line that shows nothing new would leave the board blank: move it to the next line that shows something (within 2 lines), else drop it."""
    shows = ("note", "image", "choice", "svg", "equation")
    fixed = 0
    for i, line in enumerate(script.lines):
        if any(c.kind == "clear" for c in line.cues) and not any(c.kind in shows for c in line.cues):
            line.cues = [c for c in line.cues if c.kind != "clear"]
            nxt = next((j for j in range(i + 1, min(i + 3, len(script.lines))) if any(c.kind in shows for c in script.lines[j].cues)), None)
            if nxt is not None and not any(c.kind == "clear" for c in script.lines[nxt].cues):
                script.lines[nxt].cues.insert(0, BoardCue(kind="clear"))
            fixed += 1
    return fixed


def strip_latex(script: LessonScript) -> int:
    """LaTeX in a spoken line or board note would be read aloud / shown as raw markup: convert to plain Unicode (4Al + 3O₂ → 2Al₂O₃). Returns how many texts changed."""
    n = 0
    for line in script.lines:
        for obj in [line, *line.cues]:
            if obj.text and has_latex(obj.text):
                obj.text, n = plain(obj.text), n + 1
            for i, o in enumerate(getattr(obj, "options", None) or []):
                if has_latex(o):
                    obj.options[i], n = plain(o), n + 1
    return n


async def repair(script: LessonScript, max_gap: float, model: str, md: str = "", max_scene: float = 50.0) -> tuple[LessonScript, dict]:
    script = script.model_copy(deep=True)
    latex_fixed = strip_latex(script)
    restored = restore_missing(md, script) if md else []
    latex_fixed += strip_latex(script)  # restored lecture sentences may carry it too
    stats = {"latex_fixed": latex_fixed, "restored_sentences": len(restored), "split": split_long_lines(script), "card_fixes": repair_cards(script), "scene_cues": scene_breaks(script)}
    stats["gap_notes"] = await fill_gaps(script, max_gap, model)  # notes first: a long scene can only be cut where something new appears
    stats["long_scene_splits"] = split_long_scenes(script, max_scene)
    stats["blank_clears_fixed"] = fix_blank_clears(script)
    log.info("repair", **stats, lines=len(script.lines), restored=restored)
    return script, stats
