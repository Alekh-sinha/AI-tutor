"""Answer check for the live teacher. The speech model tends to praise whatever a child says ("बिल्कुल सही!") even for a wrong or unintelligible answer, so the verdict comes from a SEPARATE text-model call
that sees the question, the expected answer, the class notes and the child's actual words (the voice transcript the server holds, not the speech model's memory of it)."""

import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION

log = logsetup.get("live")

INSTRUCTION = """You check a Class 6 child's spoken answer for their teacher. Inputs: the QUESTION, the EXPECTED ANSWER the teacher has in mind (if it says to derive it, work it out yourself from the class notes and standard school science), the CLASS NOTES (the authority for facts) and WHAT THE CHILD SAID
(an automatic transcript of their voice: it may be garbled, partial, or contain English-script Hindi words; it can also be empty).
Decide strictly, using the notes, whether the child answered the question correctly:
- correct: the essential idea is there (wording and grammar do not matter).
- partly: some of the idea is right but something essential is missing or mixed with a mistake.
- wrong: it contradicts the facts, or answers something else.
- unclear: empty, garbled, off-topic noise, or too little to judge. NEVER guess that unclear speech is correct.
Then write `teacher_should_say`: TWO or THREE short simple Hindi sentences the teacher can say next, in the teacher's voice. The question is NEVER asked again and no hint game is played. correct: a brief confirmation of exactly what was right. partly: say what was right, then give the full right answer and the reason behind it.
wrong or unclear (including "I don't know", a yes/no to a why-question, or speech that could not be made out): kindly, without scolding, give the right answer and the reason behind it, so that the child learns it now."""


class Verdict(BaseModel):
    child_said_meaning: str = Field(description="what the child seems to have said, in your own words (English), or 'nothing intelligible'")
    verdict: str = Field(description="correct | partly | wrong | unclear")
    reason: str = Field(description="one English sentence: why, with reference to the expected answer")
    teacher_should_say: str = Field(description="1-2 short Hindi sentences for the teacher to say next")


async def judge(question: str, expected: str, heard: str, notes: str) -> dict:
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    text = f"QUESTION: {question}\nEXPECTED ANSWER: {expected}\nWHAT THE CHILD SAID: {heard.strip() or '(nothing was transcribed)'}\n\nCLASS NOTES:\n{notes[:6000]}"
    r = await client.aio.models.generate_content(
        model=DEFAULT_TEXT_MODEL, contents=text,
        config=types.GenerateContentConfig(system_instruction=INSTRUCTION, response_mime_type="application/json", response_schema=Verdict, temperature=0.1))
    v = Verdict.model_validate(json.loads(r.text))
    if v.verdict not in ("correct", "partly", "wrong", "unclear"):
        v.verdict = "unclear"
    if not heard.strip():
        v.verdict = "unclear"  # hard rule: nothing transcribed can never be "correct"
    log.info("answer-judged", question=question[:160], expected=expected[:160], heard=heard[:200], verdict=v.verdict, reason=v.reason[:200])
    return v.model_dump()
