"""Output of the planning agent: how a chapter is split into lessons of at most 10 minutes."""

from pydantic import BaseModel, Field

from ai_teacher_api.common.lesson import HomeActivity, QuizQuestion


class Beat(BaseModel):
    """One teaching step inside a lesson (becomes a few narration lines + board events)."""

    idea: str = Field(description="The one concept this step teaches, in English, as in the textbook")
    technique: str = Field(
        description="Teaching move: experience-first | predict-then-reveal | contrast | analogy | story | "
        "mini-experiment | misconception-fix"
    )
    experience: str = Field(
        description="An original situation the student has personally lived, in the lesson language, "
        "told so the concept emerges from it. NOT copied from the textbook."
    )
    question: str = Field(description="The question the teacher asks the student before revealing the concept (lesson language)")
    misconception: str | None = Field(None, description="Wrong belief students commonly hold here, and how this step fixes it")
    check_question: str = Field(description="Quick oral check at the end of the step (lesson language)")
    visual: str | None = Field(None, description="What should appear on the board: note, diagram or picture")
    minutes: float = Field(description="Estimated spoken minutes for this step")
    source_pages: list[int] = Field(description="Textbook pages this step is based on")


class LessonOutline(BaseModel):
    id: str
    title: str
    objectives: list[str]
    beats: list[Beat]
    recap: str
    quiz: list[QuizQuestion]
    home_activity: HomeActivity
    source_pages: list[int]


class LessonPlan(BaseModel):
    chapter: str
    language: str
    region: str
    lessons: list[LessonOutline]
