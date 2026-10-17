"""Lesson timeline schema: the single format shared by recorded, doubt-chat and live modes.

This module is the source of truth. Run `uv run python -m ai_teacher_api.export_schema`
to regenerate packages/lesson-schema/lesson.schema.json, then keep
packages/lesson-schema/lesson.ts in sync.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Note(BaseModel):
    type: Literal["note"] = "note"
    t: float = Field(ge=0, description="Seconds from lesson start")
    id: str
    text: str
    style: Literal["heading", "body", "bullet", "key"] = "body"


class Image(BaseModel):
    type: Literal["image"] = "image"
    t: float = Field(ge=0)
    id: str
    src: str
    caption: str | None = None


class Label(BaseModel):
    """A word or phrase drawn by the player (HTML, real font) on top of an image. Positions are percentages."""

    text: str
    x: float = Field(ge=0, le=100, description="Centre, % of the image width")
    y: float = Field(ge=0, le=100, description="Centre, % of the image height")
    size: float = Field(4.6, gt=0, le=15, description="Font size as % of the image width")
    color: str | None = Field(None, description="CSS hex colour, default dark ink")
    bold: bool = False


class Svg(BaseModel):
    type: Literal["svg"] = "svg"
    t: float = Field(ge=0)
    id: str
    markup: str = Field(description="Inline SVG with NO text; sanitised before rendering")
    labels: list[Label] = []
    caption: str | None = None


class Equation(BaseModel):
    type: Literal["equation"] = "equation"
    t: float = Field(ge=0)
    id: str
    latex: str


class Highlight(BaseModel):
    type: Literal["highlight"] = "highlight"
    t: float = Field(ge=0)
    target: str = Field(description="id of an element already on the board")


class Hide(BaseModel):
    """Remove ONE element (an old note) to make room, while the rest of the scene stays."""

    type: Literal["hide"] = "hide"
    t: float = Field(ge=0)
    target: str


class Clear(BaseModel):
    type: Literal["clear"] = "clear"
    t: float = Field(ge=0)


class Choice(BaseModel):
    """A question card for the student to think about (and tap). The answer is shown at `reveal_at`."""

    type: Literal["choice"] = "choice"
    t: float = Field(ge=0)
    id: str
    question: str
    options: list[str] = Field(min_length=2, max_length=4)
    answer_index: int = Field(ge=0)
    reveal_at: float = Field(ge=0, description="Seconds when the teacher says the answer; the card marks it then")


AnimEffect = Literal["pulse", "shake", "bounce", "tick", "cross", "arrow", "glow"]


class Anim(BaseModel):
    """A short effect on an element already on the board (it is a function of time, so seeking stays consistent)."""

    type: Literal["anim"] = "anim"
    t: float = Field(ge=0)
    target: str = Field(description="id of an element already on the board")
    effect: AnimEffect
    dur: float = Field(1.6, gt=0, le=6)


Event = Annotated[
    Note | Image | Svg | Equation | Highlight | Clear | Hide | Choice | Anim, Field(discriminator="type")
]


class NarrationLine(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class Source(BaseModel):
    """Where in the textbook a claim comes from (used for teacher review)."""

    book: str
    page: int | None = None
    section: str | None = None


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(min_length=3, max_length=4)
    answer_index: int
    explanation: str


class HomeActivity(BaseModel):
    title: str
    instructions: str = Field(description="What to observe or do at home, using things found in a village home")
    submit_as: str = Field(description="photo | voice | both: what the student submits")
    rubric: list[str] = Field(description="Criteria the evaluator checks; each one observable")
    source_activity: str | None = Field(None, description="Textbook activity id adapted, e.g. 6.1")


class Lesson(BaseModel):
    id: str
    title: str
    language: str = Field(description="BCP-47, e.g. hi-IN")
    duration: float = Field(gt=0, le=600, description="Seconds; lessons are max 10 min")
    audio: str | None = Field(None, description="Single narration track; None = silent preview")
    narration: list[NarrationLine]
    events: list[Event]
    sources: list[Source] = []
    quiz: list[QuizQuestion] = Field([], description="End-of-lesson quiz, shown after the timeline ends")
    activity: HomeActivity | None = None
