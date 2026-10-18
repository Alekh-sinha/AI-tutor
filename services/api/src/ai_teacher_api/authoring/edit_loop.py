"""The review-and-edit loop. Reviewers (a strong model, several independent passes) list problems; a separate short-context EDITOR fixes exactly those.
This is the design that did best in the fix-loop experiments (see CLAUDE.md); the same editor, with other tools, is the teacher's editing agent later.

Rules enforced in code, not in prompts:
- a picture problem counts only when EVERY review pass reports it (a single pass produced false findings); text problems are the union;
- a picture the editor has already tried twice is FROZEN: its image tools are refused and the editor may only make the narration claim less, so the loop always closes;
- unresolved findings are returned for the teacher instead of looping forever.
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.agents import LlmAgent, RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.authoring import illustrator as ill
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.review import MAX_TOTAL_WORDS, IMG_REF, critique_lecture, lecture_checks, lecture_images, length_issue
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, REVIEW_MODEL, REVIEW_PASSES, resolve_model

log = logsetup.get("authoring")
MAX_ROUNDS = 3
IMAGE_BUDGET_PER_ROUND = 10
MAX_LLM_CALLS = 40
MAX_TRIES_PER_PICTURE = 2
MAX_TRIM_ROUNDS = 3


class LectureTooLong(RuntimeError):
    pass


@dataclass
class Findings:
    text: list[str] = field(default_factory=list)  # code checks + text problems from any pass
    pictures: dict[str, str] = field(default_factory=dict)  # picture id -> problem, only when every pass agrees
    doubtful: dict[str, str] = field(default_factory=dict)  # flagged by some passes only (logged, not acted on)

    def count(self) -> int:
        return len(self.text) + len(self.pictures)

    def lines(self) -> list[str]:
        return self.text + [f"[picture {k}] {v}" for k, v in self.pictures.items()]


def combine(found: Findings, results: list, picture_ids: set[str], passes: int) -> Findings:
    """Merge several review passes: text findings are the union; a picture finding counts only when EVERY pass reports it (a single pass produced false findings).
    A picture finding that slipped into a pass's text list is dropped, because the picture audit is its only channel."""
    votes: dict[str, list[str]] = {}
    for text_issues, pictures in results:
        text_issues = [t for t in text_issues if t.removeprefix("[critic] ").split(":", 1)[0].strip().removeprefix("picture ").strip() not in picture_ids]
        found.text += [t for t in text_issues if t not in found.text]
        for p in pictures:
            votes.setdefault(p.id, []).append(f"{p.problem}. Fix: {p.fix}")
    for pid, notes in votes.items():
        (found.pictures if len(notes) >= passes else found.doubtful)[pid] = max(notes, key=len)
    return found


async def review_lecture(md: str, plan_text: str, d: Path, tag: str, concepts: int) -> Findings:
    found = Findings(text=lecture_checks(md, d, concepts))

    async def one(k: int):
        got, _ = await with_model_fallback(lambda m: critique_lecture(md, plan_text, d, m, d / f"audit-{tag}-pass-{k + 1}.json"), REVIEW_MODEL)
        return got

    results = await asyncio.gather(*[one(k) for k in range(REVIEW_PASSES)])  # independent passes, run together
    combine(found, results, {n for _, n in lecture_images(md)}, REVIEW_PASSES)
    return found


# ---------------------------------------------------------------- the editor
_doc = {"md": ""}


def replace_text(old: str, new: str) -> dict:
    """Edit the lesson text: replace the passage `old` (it must appear EXACTLY ONCE in the lesson) with `new`. Use it for wording, questions, and to place a new picture reference."""
    n = _doc["md"].count(old)
    if n != 1:
        log.warn("replace-text-failed", matches=n, old=old[:120])
        return {"status": "error", "error": f"`old` appears {n} times; it must appear exactly once. Include more surrounding text."}
    _doc["md"] = _doc["md"].replace(old, new)
    return {"status": "ok"}


EDITOR = """You are the editor of an illustrated lesson for Class 6 children in rural Bihar (Hindi). A reviewer has listed problems. Fix exactly those problems and
nothing else; do not rewrite or reorganise the lesson, and keep everything that was not flagged.
For a picture problem: look at the picture, change it, and look at the result. If one edit does not fix a picture, stop editing it: simplify the lesson so that it asks for
less (change the narration and the picture description so they say only what the picture clearly shows) instead of trying again. A picture listed as FROZEN cannot be
changed any more: only the narration and the description may change, to claim only what the picture clearly shows. A text problem is fixed by editing the text.
For a stretch of narration with nothing new on screen, add one SIMPLE STILL photograph (an object, a material or a step; nothing that needs motion) with a new name
where the point changes. Pictures are photographs with no text; definitions and labels belong in the narration.
A LENGTH issue is fixed by cutting text with replace_text (use several calls, each removing one sentence or one paragraph; `new` may be empty or a shorter version):
cut examples and repetition first, never a concept's aim, its check question with options and answer, or the recap; when you remove the paragraph a picture belongs to, remove
that picture line too, and keep every picture line whose paragraph stays. Count what you cut: reach the number the issue asks for.
When every issue is handled, reply 'done' with one line per issue saying what you did.

Tools: view_picture(name); edit_image(name, change) changes only what you ask, so keep it to one concrete change; generate_image(name, prompt) only for a NEW picture;
replace_text(old, new) edits the lesson (old must appear exactly once in the lesson text)."""


def build_editor(model: str | None = None) -> LlmAgent:
    return LlmAgent(name="editor", model=resolve_model(model), instruction=EDITOR, tools=[ill.view_picture, ill.edit_image, ill.generate_image, replace_text])


async def run_editor(model: str, d: Path, md: str, findings: Findings, frozen: set[str], stats: dict) -> str:
    ill.set_budget(IMAGE_BUDGET_PER_ROUND)
    ill.set_redraw_allowed(set(findings.pictures) - frozen)
    _doc["md"] = md
    used = {n for _, n in lecture_images(md)}
    names = sorted(p.stem for p in d.glob("*.webp") if p.stem in used)
    msg = "REVIEWER FINDINGS:\n" + "\n".join(f"- {i}" for i in findings.lines()) + f"\n\nPictures that exist: {names}"
    if frozen:
        msg += f"\nFROZEN pictures (no image tool may be used on them): {sorted(frozen)}"
    msg += f"\n\nTHE LESSON:\n{md}"
    sessions = InMemorySessionService()
    runner = Runner(agent=build_editor(model), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    reply = ""
    async for e in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=msg)]),
                                    run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
        if e.is_final_response() and e.content and e.content.parts:
            reply = "".join(p.text or "" for p in e.content.parts)
        for c in e.get_function_calls():
            stats["tools"][c.name] = stats["tools"].get(c.name, 0) + 1
            print(f"[editor] {c.name} {str((c.args or {}).get('name') or '')[:80]}", flush=True)
        if e.usage_metadata:
            stats["llm_calls"] += 1
            stats["prompt_tokens"] += e.usage_metadata.prompt_token_count or 0
            stats["output_tokens"] += e.usage_metadata.candidates_token_count or 0
    stats["reply"] = reply  # the editor's own account of what it did per finding (logged: why a finding survives is visible here)
    return _doc["md"]


def archive_unused(d: Path, md: str) -> list[str]:
    """Move pictures that were drawn but are not used in the lecture into `unused/` (nothing is deleted; the teacher can bring one back). Returns their names."""
    used = {n for _, n in lecture_images(md)}
    moved = []
    for f in sorted(d.glob("*.webp")):
        if f.stem not in used:
            (d / "unused").mkdir(exist_ok=True)
            f.rename(d / "unused" / f.name)
            moved.append(f.stem)
    if moved:
        log.info("archive-unused", folder=str(d), pictures=moved)
    return moved


# ---------------------------------------------------------------- the loop
async def improve(d: Path, plan_text: str, md: str, concepts: int, model: str = DEFAULT_TEXT_MODEL, max_rounds: int = MAX_ROUNDS,
                  first: Findings | None = None) -> dict:
    """Review, then edit, up to `max_rounds` times. Writes lecture.md in `d`. Returns the lecture, per-round log and what is left for the teacher."""
    if ill._state["dir"] != d:
        ill.configure(d, ill.IMAGE_MODEL)
    tries: dict[str, int] = {}
    rounds = []
    t_all = time.time()
    findings = first or await review_lecture(md, plan_text, d, "round0", concepts)
    rounds.append({"review": 0, "findings": findings.count(), "list": findings.lines(), "doubtful": findings.doubtful})
    print(f"round 0 review: {findings.count()} finding(s) ({len(findings.doubtful)} doubtful)", flush=True)
    for rnd in range(1, max_rounds + 1):
        if not findings.count():
            break
        log_prev = findings.lines()
        frozen = {p for p in findings.pictures if tries.get(p, 0) >= MAX_TRIES_PER_PICTURE}
        for p in findings.pictures:
            tries[p] = tries.get(p, 0) + 1
        stats = {"llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "tools": {}}
        n_before, t0 = len(ill._state["attempts"]), time.time()
        new_md, _ = await with_model_fallback(lambda m: run_editor(m, d, md, findings, frozen, stats), model)
        md = new_md or md
        (d / "lecture.md").write_text(md)
        fix_s = round(time.time() - t0)
        attempts = ill._state["attempts"][n_before:]
        t1 = time.time()
        findings = await review_lecture(md, plan_text, d, f"round{rnd}", concepts)
        rounds.append({"fix_round": rnd, "fix_seconds": fix_s, "review_seconds": round(time.time() - t1), "frozen": sorted(frozen), "editor": stats,
                    "image_attempts": len(attempts), "image_attempts_rejected": sum(a["outcome"] != "ok" for a in attempts),
                    "findings": findings.count(), "list": findings.lines(), "doubtful": findings.doubtful})
        print(f"=== editor round {rnd}: {fix_s}s {stats['tools']} -> {findings.count()} finding(s)", flush=True)
        log.info("editor-round", round=rnd, seconds=fix_s, tools=stats["tools"], frozen=sorted(frozen), editor_reply=stats.get("reply", ""), findings_before=log_prev, findings_after=findings.lines())
        for i in findings.lines():
            print("  -", i[:200], flush=True)
    (d / "lecture.md").write_text(md)
    for k in range(1, MAX_TRIM_ROUNDS + 1):  # the length limit is HARD: the video is rejected above 10 minutes, so the editor keeps cutting until it fits (code counts, no reviewer needed)
        issue = length_issue(md)
        if not issue:
            break
        before = len(IMG_REF.sub("", md).split())
        stats = {"llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "tools": {}}
        new_md, _ = await with_model_fallback(lambda m: run_editor(m, d, md, Findings(text=[issue]), set(), stats), model)
        md = new_md or md
        (d / "lecture.md").write_text(md)
        after = len(IMG_REF.sub("", md).split())
        log.info("trim-round", round=k, words_before=before, words_after=after, limit=MAX_TOTAL_WORDS, reply=stats.get("reply", ""))
        print(f"=== trim round {k}: {before} -> {after} words (limit {MAX_TOTAL_WORDS})", flush=True)
        rounds.append({"trim_round": k, "words_before": before, "words_after": after})
    if length_issue(md):
        raise LectureTooLong(f"the lecture still has {len(IMG_REF.sub('', md).split())} words after {MAX_TRIM_ROUNDS} trim rounds (limit {MAX_TOTAL_WORDS}): shorten it in the Lecture tab, then build the video again")
    if any(r.get("trim_round") for r in rounds):  # the trim may have changed what the code checks look at (pictures, questions): check again
        findings = Findings(text=[t for t in findings.text if not t.startswith("[check]")] + lecture_checks(md, d, concepts), pictures=findings.pictures, doubtful=findings.doubtful)
    archived = archive_unused(d, md)  # unused pictures left after all rounds are leftovers of earlier versions: archived, not nagged about forever
    if archived:
        findings = Findings(text=[t for t in findings.text if "drawn but are not used" not in t], pictures=findings.pictures, doubtful=findings.doubtful)
    return {"md": md, "archived_unused": archived, "rounds": rounds, "for_teacher": findings.lines(), "seconds": round(time.time() - t_all)}
