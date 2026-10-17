from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from ai_teacher_api.classic.illustrate import generate_illustration
from ai_teacher_api.common.settings import resolve_model
from ai_teacher_api.classic.visuals import LessonVisuals, validate_svg

SKILLS = Path(__file__).parent / "skills"

INSTRUCTION = """You prepare the pictures for ONE lesson. The cues are of two kinds.

kind=image: call generate_illustration(cue_id, scene) once per image cue. Write `scene` in English as a vivid,
concrete PHOTOGRAPH (people with their age and clothes, the place, the objects with their colours, the light, a clear focal
point; a close-up when one object matters). No writing in the picture. If it returns ok=false, improve the scene and retry. List the ok cue ids in `images`.

kind=svg: draw a diagram as SVG, as follows.
First call load_skill for "svg-diagrams" and follow it. The user message lists the diagram cues
(id + precise description with labels). Draw exactly one SVG per cue, using the labels from the description
(spelled exactly as given). The SVG itself must contain NO text: put every word in `labels` with its centre
position in viewBox units, next to the thing it names, never overlapping shapes' key parts or other labels.
Call validate_svg(svg, labels) on each drawing and fix it until it passes, then return all assets.
Make the diagram teach: the contrast or relationship in the description must be visible at a glance."""


def build_visualizer(model: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="visualizer",
        model=resolve_model(model),
        instruction=INSTRUCTION,
        tools=[SkillToolset(skills=[load_skill_from_dir(SKILLS / "svg-diagrams")]), validate_svg, generate_illustration],
        output_schema=LessonVisuals,
        output_key="lesson_visuals",
    )
