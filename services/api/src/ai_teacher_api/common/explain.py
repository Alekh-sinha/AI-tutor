"""Ask an agent WHY it produced what it produced (for debugging; shared by the director and authoring features). The agent gets its own instruction, the material it was given and the output it produced, and
answers questions about it; the answers go to the feature log. Post-hoc explanations are not proof, but they point at the cause (prompt, input or check).

"""

import asyncio
import json
import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.resilience import with_model_fallback
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, REVIEW_MODEL


async def ask(instruction: str, material: str, output: str, question: str, model: str) -> str:
    agent = LlmAgent(name="explainer", model=model, instruction=instruction + "\n\nYou are now being interviewed about your own earlier work. Answer honestly and specifically; "
                     "say what in your instructions, input or the checks led to each choice, and what you would change. Plain text.")
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="ai-teacher", session_service=sessions)
    s = await sessions.create_session(app_name="ai-teacher", user_id="dev")
    msg = f"WHAT YOU WERE GIVEN:\n{material}\n\nWHAT YOU PRODUCED:\n{output}\n\nQUESTION: {question}"
    out = ""
    async for e in runner.run_async(user_id="dev", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
        if e.is_final_response() and e.content:
            out += "".join(p.text or "" for p in e.content.parts)
    return out


