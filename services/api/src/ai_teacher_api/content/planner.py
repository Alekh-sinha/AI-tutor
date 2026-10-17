from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from ai_teacher_api.content.plan import LessonPlan
from ai_teacher_api.common.settings import resolve_model

SKILLS = Path(__file__).parent / "skills"

INSTRUCTION = """You plan spoken classroom lessons from a textbook chapter.
First call load_skill for "lesson-planning" (and load_skill_resource for the regional file that
matches the requested region), then follow it exactly. The user message contains the settings
(language, region, grade) and the page-tagged chapter text. Return the plan as the required JSON.
Write `idea`, `technique`, `misconception`, `visual` and `objectives` in English. Write everything the
student will hear or read (`title`, `experience`, `question`, `check_question`, `recap`, quiz, home activity) in the
lesson language, in simple spoken style. Be inventive: your examples must be your own, not the book's."""


def build_planner(model: str | None = None) -> LlmAgent:
    skills = SkillToolset(skills=[load_skill_from_dir(SKILLS / "lesson-planning")])
    return LlmAgent(
        name="planner",
        model=resolve_model(model),
        instruction=INSTRUCTION,
        tools=[skills],
        output_schema=LessonPlan,
        output_key="lesson_plan",
    )
