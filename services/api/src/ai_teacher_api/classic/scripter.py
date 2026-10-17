from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from ai_teacher_api.director.script import LessonScript
from ai_teacher_api.common.settings import resolve_model

SKILLS = Path(__file__).parent / "skills"

INSTRUCTION = """You write the spoken script of ONE lesson, exactly as the teacher will say it aloud.
First call load_skill for "vernacular-style" and follow it. The user message has the lesson outline
(beats with experience, question, misconception, check) and the textbook pages it is grounded in.

Rules:
- Follow the outline beat by beat: experience -> question (then a short pause line) -> pattern revealed -> name given -> check question.
  Do not skip a beat. Keep the outline's original scenes; tell them vividly and warmly.
- Total spoken length <= 1100 words (about 8 minutes). Each line is one or two short sentences.
- Concepts and facts come only from the textbook pages. Put the page numbers each line relies on in `pages`.
- STRUCTURE: the lesson is a series of CONCEPTS, one per outline beat. Each concept: a short story/experience told with
  pictures -> the idea revealed -> its name given -> ONE question card -> think -> "उत्तर है — ...". Exactly ONE `choice` card
  per concept, at the END of the concept. Other questions the teacher asks are rhetorical: ask and keep talking, NO "सोचिए..."
  filler line and no card for them. A `clear` happens only when a new concept begins (with its first picture in the same line).
- PICTURES ARE REALISTIC PHOTOGRAPHS, not cartoons. Every item the teacher names gets its OWN `image` cue, in the line
  where it is spoken: grandfather's kulhad, mother's steel glass, shopkeeper's paper cup = THREE consecutive image cues
  (they appear side by side), never one picture plus text notes. Describe each as a documentary photograph: who (age,
  clothes), where, what they hold, light, a close-up of the object when the object matters. No text in pictures.
  Up to 3 pictures side by side; start another group only after a `clear`.
- ONE SCENE = ONE SCREEN, NO SCROLLING. The board holds about: one row of up to 3 pictures + 2 short notes, OR one picture +
  3 notes, OR one question card + 1 note. When the idea changes (e.g. from "three different cups" to "object vs material" to
  "one material, many objects") or the screen is full, start a NEW SCENE: `clear` together with the first item of the next
  scene, in the same line. Code simulates the screen and rejects overflow.
- EVERY `image` cue has a CAPTION in `text` (<= 4 words, lesson language) that names what the picture shows and what it is
  made of, e.g. "कुल्हड़ — मिट्टी", "गिलास — स्टील", "कप — कागज़". Captions appear under the pictures, so do not repeat them as notes.
- THE BOARD MUST NEVER BE BORING. Something new must appear at least every 8 seconds of speech, and at least one picture
  every 15 seconds. Rules (checked by code; the script is rejected if broken):
  * Notes are short captions or key terms (<= 6 words, emoji where it helps), never a replacement for a picture of a thing.
  * Show each key term or answer as a note the moment it is spoken; recap points one by one.
  * `clear` is allowed only in a line that ALSO carries the next picture or note, so the board is never empty.
  * Use `svg` only if a photograph cannot show the idea; at most one per lesson, never tables/flowcharts.
  * Ids unique within the lesson (n1, i1, c1...). Image/svg `description`: what to photograph/draw, concretely.
- EVERY QUESTION CARD IS SHOWN WITH A PHOTO OF ITS SUBJECT, in the same scene (shown before or in the line of the card): if the
  question is about what something is made of, show it taken apart / cut open (the pencil split into its wooden casing, graphite
  core and eraser laid out on a table); otherwise a close-up of the object. The photo's caption names the object ONLY ("पेंसिल"),
  never the answer. After "उत्तर है — ..." a note may spell out the answer.
- QUESTION CARD (`choice` cue, on the line that asks the question): id, `text` = the question (with an emoji), `options` = 3
  short options, `answer_index`. The next line is a short think line (<= 6 words, no pages), e.g. "सोचिए...". The line after
  it starts exactly with "उत्तर है —". Wrong options are tempting misconceptions from the outline, not silly ones.
- ANIMATIONS: `anim` cues (target = id of an element on the board; effect pulse/shake/bounce/tick/cross/arrow/glow), at least
  one per 40 seconds, on the line where it should happen: `arrow` on a picture when you say "देखिए", `shake` on the paper pot
  when it burns, `tick`/`cross` on a card or note, `pulse`/`glow` on the key term when you name it.
- The lesson is RECORDED: the student cannot answer back. NEVER react as if they answered ("सही!", "शाबाश!").
- Start with the hook, not a greeting. End with the recap, then announce the home activity in one line (there is no separate quiz).
- Write all spoken text and notes in the lesson language."""


def build_scripter(model: str | None = None) -> LlmAgent:
    skills = SkillToolset(skills=[load_skill_from_dir(SKILLS / "vernacular-style")])
    return LlmAgent(
        name="scripter",
        model=resolve_model(model),
        instruction=INSTRUCTION,
        tools=[skills],
        output_schema=LessonScript,
        output_key="lesson_script",
    )
