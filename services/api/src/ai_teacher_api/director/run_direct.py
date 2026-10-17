"""Agent 2 stage: illustrated lecture (+ pictures) -> video script (checked in code and by the storyboard reviewer) -> narration audio -> playable lesson.

uv run python -m ai_teacher_api.run_direct ../../data/ch6 lesson-1 [--lecture-dir DIR] [--out-id lesson-1-new] [--no-audio]
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.common import tracing
from ai_teacher_api.director.agent import Directed, build_director
from ai_teacher_api.director.assemble import assemble
from ai_teacher_api.content.brief import LessonBrief, render
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.authoring.review import IMG_REF, lecture_images, review_script
from ai_teacher_api.common import logsetup
from ai_teacher_api.director import repair
from ai_teacher_api.director.script import LessonScript, rhythm_problems, scene_spans
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, DEFAULT_VOICE, WEB_PUBLIC
from ai_teacher_api.common.tts import narrate

log = logsetup.get("director")
MAX_SCENE_SECONDS = 50.0  # one scene = one idea (a picture group with its notes); longer means ideas were not separated
PICTURE_EVERY = 10_000.0  # picture density is Agent 1's job (review.attention_gaps), not the director's
MAX_GAP = 20.0  # seconds without a new board item; the lecture style writes a note per point, not per sentence
COVERAGE_MIN, INVENTION_MAX = 0.8, 0.3
WORD = re.compile(r"[ऀ-ॿ]+")


def fidelity_problems(md: str, script: LessonScript) -> list[str]:
    """The director may split and smooth the narration but not drop or invent content (a rough word-overlap check)."""
    src = set(WORD.findall(" ".join(repair.lecture_sentences(md))))  # the narrated part of the lecture (not options, aims, the home-activity section)
    said = set(WORD.findall(" ".join(l.text for l in script.lines)))
    if not src or not said:
        return ["[fidelity] no narration found"]
    out = []
    coverage, invention = len(src & said) / len(src), len(said - src) / len(said)
    if coverage < COVERAGE_MIN:
        out.append(f"[fidelity] only {coverage:.0%} of the lecture's words are spoken: the narration drops content; say everything the lecture teaches")
    if invention > INVENTION_MAX:
        out.append(f"[fidelity] {invention:.0%} of the spoken words are not in the lecture: do not add or change content")
    return out


def picture_problems(md: str, script: LessonScript) -> list[str]:
    want = [n for _, n in lecture_images(md)]
    used_all = [c.id for l in script.lines for c in l.cues if c.kind == "image"]
    used = [u for u in used_all if "~" not in u]  # `name~q` = the same picture shown again in its question scene (added by repair)
    out = [f"[pictures] picture {n} of the lecture is never shown on the board" for n in dict.fromkeys(want) if n not in used]
    out += [f"[pictures] image cue {u!r} is not a picture of the lecture; use only the lecture's file names" for u in used_all if u.split("~")[0] not in want]
    out += [f"[pictures] picture {u} is shown more than once" for u in dict.fromkeys(used) if used.count(u) > 1]
    if any(c.kind == "svg" for l in script.lines for c in l.cues):
        out.append("[pictures] no svg cues: use only the lecture's pictures")
    return out


def scene_problems(script: LessonScript) -> list[str]:
    return [f"[scenes] the scene from line {a} to line {b} lasts {sec:.0f}s (max {MAX_SCENE_SECONDS:.0f}s): put a `clear` with the first item of the next idea earlier" for a, b, sec in scene_spans(script) if sec > MAX_SCENE_SECONDS]


def checks(md: str, script: LessonScript, concepts: int) -> list[str]:
    return rhythm_problems(script, concepts, PICTURE_EVERY, MAX_GAP, show_questions=False) + picture_problems(md, script) + fidelity_problems(md, script) + scene_problems(script)


async def _direct(md: str, plan_text: str, model: str, previous: Directed | None, problems: list[str]) -> Directed:
    sessions = InMemorySessionService()
    runner = Runner(agent=build_director(model), app_name="ai-teacher", session_service=sessions)
    session = await sessions.create_session(app_name="ai-teacher", user_id="teacher")
    text = f"PLAN:\n{plan_text}\n\nLESSON (markdown):\n{md}"
    if previous and problems:
        text += ("\n\nYOUR PREVIOUS VERSION WAS REJECTED by the checks. Output the WHOLE script again, keeping what was good, and fix every problem:\n"
                 + "\n".join(f"- {p}" for p in problems) + "\n\nChange only what the problems name; keep every other line and cue exactly as it is.\n\nPREVIOUS VERSION:\n" + previous.model_dump_json())
    async for _ in runner.run_async(user_id="teacher", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        pass
    session = await sessions.get_session(app_name="ai-teacher", user_id="teacher", session_id=session.id)
    return Directed.model_validate(session.state["directed"])


def direct(md: str, plan_text: str, concepts: int, model: str, rounds: int = 3) -> tuple[Directed, list[str]]:
    """Director -> code checks + storyboard review -> back to the director. Returns the script and any problems left (for the teacher)."""
    directed, problems = None, []
    best: tuple[int, Directed, list[str]] | None = None
    for r in range(1, rounds + 1):
        directed, used = asyncio.run(with_model_fallback(lambda m: _direct(md, plan_text, m, directed, problems), model))
        raw = checks(md, directed.script, concepts)
        directed.script, fixed = asyncio.run(repair.repair(directed.script, MAX_GAP, model, md, MAX_SCENE_SECONDS))  # structure is enforced in code
        problems = checks(md, directed.script, concepts)
        log.info("round", n=r, model=used, problems_raw=raw, repairs=fixed, problems_after_repair=problems, scenes=len(scene_spans(directed.script)))
        reviewed, _ = asyncio.run(with_model_fallback(lambda m: review_script(directed.script, m), model))
        problems += reviewed
        print(f"director round {r} ({used}): {len(raw)} raw -> {len(problems) - len(reviewed)} after repair (+{len(reviewed)} from the storyboard reviewer)", flush=True)
        log.info("reviewer", n=r, issues=reviewed)
        for p in problems:
            print("  -", p[:220], flush=True)
        if best is None or len(problems) < best[0]:
            best = (len(problems), directed, problems)
        if not problems:
            break
    return best[1], best[2]  # the best round, not the last (a rewrite can make things worse)


def register(lesson_id: str, title: str, duration: float, status: str | None = None) -> None:
    """Add/update a lesson in the player's list. A rebuild keeps the lesson's status (a published lesson stays published); a new one is a draft."""
    f = WEB_PUBLIC / "lessons" / "index.json"
    old = json.loads(f.read_text()) if f.exists() else []
    prev = next((e for e in old if e["id"] == lesson_id), None)
    index = [e for e in old if e["id"] != lesson_id]
    index.append({"id": lesson_id, "title": title, "duration": duration, "status": status or (prev["status"] if prev else "draft")})
    f.write_text(json.dumps(index, ensure_ascii=False, indent=1))


def produce(d: Path, lesson_id: str, out_id: str, src: Path, directed: Directed, md: str, voice: str = DEFAULT_VOICE) -> dict:
    """Script -> voice (TTS per line) -> assembled lesson JSON in the player's folder. Used after directing and after every video edit (no director call needed)."""
    chapter = json.loads((d / "chapter.json").read_text())
    directed.script.language, directed.script.lesson_id = "hi-IN", out_id
    mp3, timings = asyncio.run(narrate(directed.script, voice=voice))
    (d / "audio").mkdir(exist_ok=True)
    (d / "audio" / f"{out_id}.mp3").write_bytes(mp3)
    (d / f"timings-{out_id}.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1))
    (WEB_PUBLIC / "audio").mkdir(exist_ok=True)
    (WEB_PUBLIC / "audio" / f"{out_id}.mp3").write_bytes(mp3)
    img_out = WEB_PUBLIC / "img"
    img_out.mkdir(exist_ok=True)
    srcs = {}
    for _, name in lecture_images(md):
        f = src / f"{name}.webp"
        if f.exists():
            (img_out / f"{out_id}-{name}.webp").write_bytes(f.read_bytes())
            srcs[name] = f"/img/{out_id}-{name}.webp"
    for l in directed.script.lines:  # a recalled picture (`name~q`) uses the same file
        for c in l.cues:
            if c.kind == "image" and "~" in (c.id or "") and c.id.split("~")[0] in srcs:
                srcs[c.id] = srcs[c.id.split("~")[0]]
    lesson = assemble(directed.script, timings, f"/audio/{out_id}.mp3", chapter["book"], {}, srcs, [], directed.activity.model_dump())
    (WEB_PUBLIC / "lessons" / f"{out_id}.json").write_text(json.dumps(lesson.model_dump(), ensure_ascii=False, indent=1))
    register(out_id, lesson.title + (" · v2" if out_id != lesson_id else ""), lesson.duration)
    log.info("produced", lesson=out_id, duration=round(lesson.duration), events=len(lesson.events), lines=len(directed.script.lines))
    return {"duration": round(lesson.duration), "events": len(lesson.events)}


def run(d: Path, lesson_id: str, model: str = DEFAULT_TEXT_MODEL, voice: str = DEFAULT_VOICE, lecture_dir: Path | None = None,
        out_id: str | None = None, audio: bool = True, redo: bool = False) -> dict:
    out_id = out_id or lesson_id
    src = lecture_dir or d / "illustrated" / lesson_id
    md = (src / "lecture.md").read_text()
    plan = json.loads((d / "plan.json").read_text())
    chapter = json.loads((d / "chapter.json").read_text())
    outline = next(l for l in plan["lessons"] if l["id"] == lesson_id)
    plan_text = render(LessonBrief.model_validate_json((d / f"brief-{lesson_id}.json").read_text()))
    tracing.init()
    saved = d / f"directed-{out_id}.json"
    if not redo and saved.exists() and saved.stat().st_mtime >= (src / "lecture.md").stat().st_mtime:  # resume: the script is newer than the lecture it came from
        directed = Directed.model_validate_json(saved.read_text())
        left = checks(md, directed.script, len(outline["beats"]))  # the code checks again (the storyboard reviewer is not re-run)
        print("[direct] reusing the saved script", flush=True)
    else:
        directed, left = direct(md, plan_text, len(outline["beats"]), model)
    directed.script.language, directed.script.lesson_id = "hi-IN", out_id  # the voice name needs the exact locale
    saved.write_text(directed.model_dump_json(indent=1))
    (d / f"script-{out_id}.json").write_text(json.dumps(directed.script.model_dump(), ensure_ascii=False, indent=2) + "\n")
    result = {"lesson": out_id, "for_teacher": left, "lines": len(directed.script.lines)}
    if audio:
        result.update(produce(d, lesson_id, out_id, src, directed, md, voice))
    (d / f"direct-{out_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    tracing.flush()
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("lesson_id")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--lecture-dir")
    ap.add_argument("--out-id")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--redo", action="store_true", help="ignore the saved script and direct again")
    a = ap.parse_args()
    run(Path(a.dir), a.lesson_id, a.model, a.voice, Path(a.lecture_dir) if a.lecture_dir else None, a.out_id, not a.no_audio, a.redo)


if __name__ == "__main__":
    main()
