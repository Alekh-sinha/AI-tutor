"""The board assistant of the live class. Why it exists: when the speech model calls a tool WHILE it is talking, a large part of what it says is silently dropped from the audio (measured 2026-10-15:
~3.0 words/s of audio without tools, 8.0 words/s with tool calls in the middle = more than half of the sentences lost, although the transcript/captions still showed them).
So the teacher only talks; after every teacher turn this separate text-model call reads the transcript and decides what goes on the board (key words, a lesson picture or a new picture, a new scene),
tied to the sentence it belongs to, so the clients show it exactly when that sentence is spoken. It also writes the class plan and notices when the class is over."""

import asyncio
import json
import re
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION
from ai_teacher_api.tutor import agent as tutor

log = logsetup.get("live")

INSTRUCTION = """You run the blackboard of a live Hindi class for Class 6 children watching on a phone. The teacher only talks; YOU decide what appears on the board while she talks.
Each time you get what the teacher just said (numbered sentences) and what is on the board now. Decide:
- new_scene: true when this turn starts a new idea/step (the board is wiped first). False when it continues the same idea or only reacts to a child's answer or question.
- ops: at most 3 short notes and at most ONE picture for this turn, each tied to the sentence where it should appear (after_sentence = number of the sentence that introduces it; 0 = at the very start).
  A note = a key word or short fact in Hindi, at most 6 words (the `text` field is REQUIRED for a note) (style "key" for the main term, "heading" for a step title, else "body"); never a whole sentence, never the question itself.
  A picture helps the child SEE what the teacher describes: use a lesson picture (kind lesson_picture, name from the list) if one clearly fits what is being said; otherwise, when the teacher describes something visible and concrete
  (an object, a material, a simple scene), use kind draw_picture with an English description of ONE still, simple photograph (one or two objects or a person doing something simple; never motion, collapsing, pouring, exact counts,
  tiny parts or text/labels in the picture) in at most 30 words, and a Hindi caption of at most 4 words. Put the picture early in the turn (after_sentence 0 or 1). No picture for greetings, questions to the class, or pure reactions.
- plan: ONLY if the plan is still empty: 3-5 very short Hindi steps of the whole class (from the class notes / what she said). Otherwise an empty list.
- class_finished: true ONLY if the teacher in this turn gave the recap and home activity of the lesson and invited the children's questions.
Be sparing: a clean board is better than a crowded one."""


class Op(BaseModel):
    after_sentence: int = Field(0, description="index of the sentence (as numbered) at which this appears")
    kind: Literal["note", "lesson_picture", "draw_picture"]
    text: str = Field("", description="note: the Hindi words (<= 6 words)")
    style: Literal["heading", "body", "key"] = "body"
    name: str = Field("", description="lesson_picture: a name from the list")
    caption: str = Field("", description="pictures: <= 4 Hindi words")
    description: str = Field("", description="draw_picture: English description of one still simple photograph")


class BoardPlan(BaseModel):
    new_scene: bool
    ops: list[Op] = []
    plan: list[str] = []
    class_finished: bool = False


def sentences(said: str) -> list[tuple[int, str]]:
    """(character offset, text) of each sentence of the turn transcript; offsets index into the same string the clients assemble from the caption pieces."""
    return [(m.start(), m.group().strip()) for m in re.finditer(r"[^.?!।]+[.?!।]*\s*", said) if m.group().strip()]


def offset_of(parts: list[tuple[int, str]], k: int) -> int:
    return parts[min(max(k, 0), len(parts) - 1)][0] if parts else 0


async def decide(said: str, board_now: list[dict], plan: list[str], pictures: dict[str, str], notes: str) -> BoardPlan:
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    parts = sentences(said)
    on_board = [e.get("text") or f"[picture: {e.get('caption', '')}]" for e in board_now]
    text = (f"PLAN SO FAR: {plan or 'empty'}\nON THE BOARD NOW: {on_board or 'empty'}\nLESSON PICTURES (name: caption): {'; '.join(f'{k}: {v}' for k, v in pictures.items()) or 'none'}\n\n"
            f"CLASS NOTES (short):\n{notes[:3500]}\n\nTHE TEACHER JUST SAID:\n" + "\n".join(f"{i}. {t}" for i, (_, t) in enumerate(parts)))
    r = await client.aio.models.generate_content(
        model=DEFAULT_TEXT_MODEL, contents=text,
        config=types.GenerateContentConfig(system_instruction=INSTRUCTION, response_mime_type="application/json", response_schema=BoardPlan, temperature=0.5))
    d = BoardPlan.model_validate(json.loads(r.text))
    for o in d.ops:  # a runaway description (the model sometimes loops) is cut at a word boundary
        if len(o.description) > 260:
            o.description = o.description[:260].rsplit(" ", 1)[0]
    return d


async def run(room, turn: tutor.Turn, said: str, turn_no: int, pictures_caps: dict[str, str]) -> None:
    """After a teacher turn: decide the board, then push the events (each tagged with the turn and the character offset where it belongs)."""
    if len(said.strip()) < 25:
        return
    tutor.CURRENT.set(turn)
    try:
        d = await decide(said, list(turn.board), room.plan, pictures_caps, room.notes)
    except Exception as e:  # noqa: BLE001 - a class without a board assistant still talks
        log.error("board-failed", room=room.code, error=repr(e)[:300])
        return
    parts = sentences(said)
    log.info("board-plan", room=room.code, turn=turn_no, new_scene=d.new_scene, ops=[o.model_dump(exclude_defaults=True) for o in d.ops], plan=d.plan, finished=d.class_finished)
    if d.plan and not room.plan:
        await tutor.plan(d.plan)
    if d.class_finished and not room.finished:
        room.finished = True
        await room.broadcast(room.public_state())
        log.info("class-finished", room=room.code)
    tutor.META.set({"turn": turn_no, "at_char": 0})
    if d.new_scene:
        await tutor.clear_board()
    for op in sorted(d.ops, key=lambda o: o.after_sentence)[:4]:
        meta = {"turn": turn_no, "at_char": offset_of(parts, op.after_sentence)}
        if op.kind == "note" and op.text.strip():
            tutor.META.set(meta)
            await tutor.write_on_board(op.text, op.style)
        elif op.kind == "lesson_picture" and op.name in turn.lesson_pictures:
            tutor.META.set(meta)
            await tutor.show_lesson_picture(op.name, op.caption)
        elif op.kind == "draw_picture" and op.description.strip():
            tutor.META.set({})  # the picture appears when it is ready (up to a minute), not at a fixed point of the speech
            asyncio.create_task(tutor.draw_picture(op.description, op.caption))
    tutor.META.set({})
