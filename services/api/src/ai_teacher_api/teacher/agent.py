"""The teacher's editing assistant: the same editor tools as the review loop (view_picture, edit_image, generate_image, replace_text), driven by the teacher's
chat instead of by reviewer findings. It works on a COPY of the lesson; the teacher sees the difference and accepts or rejects it.
"""

import contextvars

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.genai import types

from ai_teacher_api.safety import policy
from ai_teacher_api.authoring.edit_loop import replace_text
from ai_teacher_api.common.settings import resolve_model
from ai_teacher_api.authoring import illustrator as ill

ASKED: contextvars.ContextVar[list] = contextvars.ContextVar("asked")


async def ask_teacher(question: str) -> dict:
    """Ask the teacher ONE specific clarifying question instead of editing (use it when the request is wide or ambiguous), then stop and wait for the answer.

    Args:
        question: the question, with the options you see, in the teacher's language.
    """
    ASKED.get().append(question)
    return {"status": "ok", "note": "the question is shown to the teacher; make no edits and finish your turn now"}


INSTRUCTION = """You are the editing assistant of a teacher who is reviewing an illustrated lesson (a Hindi lecture in markdown plus its pictures) that an AI made for Class 6 children
in rural Bihar. The teacher tells you, in Hindi or English (typed, spoken or with a photo), what to change. Do what they ask and keep everything else exactly as it is.

- Small, clear request: do it with your tools, then reply in one or two sentences, in the teacher's language, saying what you changed. For a picture change, look at the result.
- WIDE or ambiguous request (it touches many paragraphs or pictures, changes what the lesson teaches, or you cannot tell what they mean): make NO edits; call ask_teacher with ONE
  specific question that offers the options you see.
- The BOOK POINTS in the message are the authority for facts. If the request would contradict them, ask the teacher first.
- If the teacher selected a passage or a picture, the change belongs there. Pictures are realistic photographs with no text or brand names; keep the lesson's simple Hindi and its
  structure (one check question with options A, B, C and a [Pause] line per concept, the recap and the home activity).
Tools: view_picture(name); edit_image(name, change) changes only what you ask; generate_image(name, prompt) for a NEW picture with a new name; replace_text(old, new) edits the lecture
(old must appear exactly once); ask_teacher(question)."""
INSTRUCTION += "\n\n" + policy.POLICY


def build_teacher_editor(model: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="teacher_editor", model=resolve_model(model), instruction=INSTRUCTION,
        tools=[ill.view_picture, ill.edit_image, ill.generate_image, replace_text, ask_teacher],
        planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)),
    )
