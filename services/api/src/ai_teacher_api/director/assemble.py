"""Step 6: LessonScript + narration timings (+ optional visuals) -> playable Lesson timeline."""

from ai_teacher_api.common.lesson import Anim, Choice, Clear, Equation, Hide, HomeActivity, Image, Lesson, NarrationLine, Note, QuizQuestion, Source, Svg
from ai_teacher_api.director.script import ANSWER_PREFIX, LessonScript, paginate

CUE_DELAY = 0.2  # board item appears just after the line starts


def assemble(
    script: LessonScript,
    timings: list[dict],
    audio_url: str | None,
    book: str,
    svg_assets: dict[str, dict] | None = None,
    image_srcs: dict[str, str] | None = None,
    quiz: list[dict] | None = None,
    activity: dict | None = None,
) -> Lesson:
    script = paginate(script)  # scene breaks so nothing scrolls
    svg_assets = svg_assets or {}
    image_srcs = image_srcs or {}
    events, skipped = [], []
    for i, (line, tm) in enumerate(zip(script.lines, timings, strict=True)):
        t = tm["start"] + CUE_DELAY
        for c in line.cues:
            if c.kind == "clear":
                events.append(Clear(t=tm["start"]))
            elif c.kind == "hide":
                events.append(Hide(t=tm["start"], target=c.target))
            elif c.kind == "note":
                events.append(Note(t=t, id=c.id, text=c.text, style=c.style))
            elif c.kind == "equation":
                events.append(Equation(t=t, id=c.id, latex=c.text))
            elif c.kind == "choice":
                reveal = next((timings[j]["start"] for j in range(i + 1, len(timings)) if script.lines[j].text.startswith(ANSWER_PREFIX)), tm["end"])
                events.append(Choice(t=t, id=c.id, question=c.text, options=c.options, answer_index=c.answer_index, reveal_at=reveal))
            elif c.kind == "anim":
                events.append(Anim(t=t, target=c.target, effect=c.effect))
            elif c.kind == "svg" and c.id in svg_assets:
                events.append(Svg(t=t, id=c.id, markup=svg_assets[c.id]["svg"], labels=svg_assets[c.id]["labels"]))
            elif c.kind == "image" and c.id in image_srcs:
                events.append(Image(t=t, id=c.id, src=image_srcs[c.id], caption=c.text))
            else:
                skipped.append(c.id)  # svg/image without generated asset yet
    pages = sorted({p for l in script.lines for p in l.pages})
    duration = timings[-1]["end"] + 1.0
    lesson = Lesson(
        id=script.lesson_id,
        title=script.title,
        language=script.language,
        duration=duration,
        audio=audio_url,
        narration=[NarrationLine(start=t["start"], end=t["end"], text=t["text"]) for t in timings],
        events=events,
        sources=[Source(book=book, page=p) for p in pages],
        quiz=[QuizQuestion.model_validate(q) for q in quiz or []],
        activity=HomeActivity.model_validate(activity) if activity else None,
    )
    if skipped:
        print(f"[assemble] {len(skipped)} cue(s) without assets skipped: {skipped}")
    return lesson
