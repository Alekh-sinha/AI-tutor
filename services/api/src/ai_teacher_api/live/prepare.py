"""PLANNING STAGE of a topic class: everything slow is made BEFORE the teacher starts talking, so nothing slow happens while the class runs.
Steps: (1) class notes with Google Search (tutor/prep.py); (2) the KIT: a planner (text model) supplies the teacher with steps, ~4 ILLUSTRATIONS and 7-8 HTML FIGURES, each with an `intent` (the one thing a child should understand from it);
(3) illustrations are drawn in parallel on two image models (common/picturegen.py), figures are written by a text model (live/figures.py); (4) a vision model LOOKS at every drawn picture: what it really shows, whether it carries the intent by itself,
what to point out; a picture that does not communicate is redrawn once; (5) the result is the teacher's CATALOG (what each item really shows) which goes into her instruction. Pictures are saved under apps/web/public/chat/class-<code>/.
Progress is sent to the children as `thinking` events."""

import asyncio
import json
import re
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ai_teacher_api.common import logsetup, picturegen
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION, WEB_PUBLIC
from ai_teacher_api.live import figures
from ai_teacher_api.tutor import prep

log = logsetup.get("live")
MAX_PICTURES = 5
PICTURES_RANGE = (4, 6)
FIGURES_RANGE = (6, 9)
MAX_FIGURES = 8
PREP_BUDGET_S = 600  # the children wait at most this long for the pictures (the user accepted up to 10 minutes)

# the live teacher's pictures may be illustrations (the user accepted cartoons here; recorded lessons keep their photographs)
LIVE_STYLE = (
    "Friendly children's-book illustration, flat bright colours, bold clear shapes, expressive faces and body language, simple everyday Indian village setting and clothing, uncluttered background, "
    "readable at a glance on a small phone screen. ABSOLUTELY NO text, letters, numbers, logos or signs anywhere. Scene: "
)

PLANNER = """You are the resource maker for a teacher who is about to teach a LIVE VOICE CLASS to Class 6 children (11-12 years, Hindi medium, rural Bihar). The teacher speaks; the children look at a board that shows one screen at a time.
Children understand best when what they SEE tells the same story as what they HEAR. Your job is to supply the pictures and figures the teacher will put on that board, from the class notes.
Make:
- `steps`: 3-5 class steps, each a short Hindi phrase, in teaching order.
- `pictures`: 5 ILLUSTRATIONS (some may be rejected later, so make each one count). Each must carry its idea BY ITSELF: a child who looks at it without hearing a word can tell what is happening and why it matters. For every picture first decide its `intent`: the one thing a child should understand from it.
  Then describe ONE frozen moment in which that idea is visible: the people or things DOING the thing, with the cause and its visible effect in the same frame (effort shown in the body, a mark or change left behind, a before and an after side by side in one image).
  A picture of objects that merely stand there says nothing: never do that. Everyday Bihar setting, few elements, bold and clear. Never ask for text, labels, numbers or arrows inside a picture. `description`: concrete English, at most 40 words.
- `figures`: 7 or 8 HTML FIGURES for what a picture cannot show: named parts with labels, a comparison as a table, a scale or number line, cause -> effect in 2-3 boxes, steps in order, a quantity as blocks, a small animation of a change. Each is ONE simple board figure (3-6 elements, a few Hindi words) with its own `intent`.
  `description`: English instruction to the figure writer that spells out EXACTLY which Hindi labels to show and how they are arranged, at most 70 words; never ask for drawings of objects or people (the pictures do that) and no diagonal lines or curves.
Every step must have at least one picture or figure; spread them over the steps. `caption`: at most 4 Hindi words. `name`: short lowercase ASCII id (letters, digits, underscore) that starts with p for pictures and f for figures. `step`: the step it belongs to (copy the step's phrase)."""


class PicSpec(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]{2,30}$")
    step: str
    intent: str = Field(max_length=300, description="the one thing a child should understand from this item")
    description: str = Field(max_length=500)
    caption: str = Field(max_length=40)


class KitPlan(BaseModel):
    steps: list[str]
    pictures: list[PicSpec]
    figures: list[PicSpec]


def _dedupe(specs: list[PicSpec], seen: set[str]) -> list[PicSpec]:
    out = []
    for s in specs:
        if s.name not in seen:
            seen.add(s.name)
            out.append(s)
    return out


def kit_problems(k: KitPlan) -> list[str]:
    """Hard checks on the planner's output (counts and coverage), in code."""
    p = []
    if not 3 <= len(k.steps) <= 6:
        p.append(f"{len(k.steps)} steps (need 3-5)")
    if not PICTURES_RANGE[0] <= len(k.pictures) <= PICTURES_RANGE[1]:
        p.append(f"{len(k.pictures)} pictures (need about 5)")
    if not FIGURES_RANGE[0] <= len(k.figures) <= FIGURES_RANGE[1]:
        p.append(f"{len(k.figures)} figures (need 7 or 8)")
    covered = {s.step for s in k.pictures + k.figures}
    missing = [x for x in k.steps if x not in covered]
    if missing:
        p.append(f"steps without any picture or figure: {missing}")
    return p


async def plan_kit(notes: str) -> KitPlan:
    """The planner (text model) makes the kit; counts and coverage are checked in code and the planner is asked again once with the problems."""
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    contents = f"CLASS NOTES:\n{notes[:6000]}"
    kit = None
    for attempt in range(2):
        r = await client.aio.models.generate_content(
            model=DEFAULT_TEXT_MODEL, contents=contents,
            config=types.GenerateContentConfig(system_instruction=PLANNER, response_mime_type="application/json", response_schema=KitPlan, temperature=0.4))
        kit = KitPlan.model_validate(json.loads(r.text))
        seen: set[str] = set()
        kit.pictures, kit.figures = _dedupe(kit.pictures, seen)[:MAX_PICTURES + 1], _dedupe(kit.figures, seen)[:MAX_FIGURES]
        problems = kit_problems(kit)
        log.info("kit-plan", attempt=attempt, steps=len(kit.steps), pictures=len(kit.pictures), figures=len(kit.figures), problems=problems)
        if not problems:
            return kit
        contents += f"\n\nYour previous kit had these problems: {'; '.join(problems)}. Fix exactly them."
    return kit


async def make_pictures(code: str, specs: list[PicSpec], progress) -> dict[str, dict]:
    """Draw the planned pictures in parallel, paced by the per-model image quotas (common/picturegen.py). Waits at most PREP_BUDGET_S; the class starts with whatever is ready.
    Returns {name: {"src": url, "caption": ..., "step": ...}} for those that succeeded."""
    if not specs:
        return {}
    out_dir = WEB_PUBLIC / "chat" / f"class-{code}"
    pics: dict[str, dict] = {}
    done = 0

    async def one(s: PicSpec) -> None:
        nonlocal done
        res = await picturegen.draw(s.description, out_dir / f"{s.name}.webp", LIVE_STYLE)
        log.info("class-picture", room=code, name=s.name, status=res.get("status"), model=res.get("model", ""), seconds=res.get("seconds", ""), error=res.get("error", ""), description=s.description[:160])
        done += 1
        if res.get("status") == "ok":
            pics[s.name] = {"src": f"/chat/class-{code}/{s.name}.webp", "caption": s.caption, "step": s.step, "intent": s.intent, "description": s.description}
        await progress(f"चित्र बन रहे हैं… {done}/{len(specs)}")

    await progress(f"चित्र बन रहे हैं… 0/{len(specs)}")
    tasks = [asyncio.create_task(one(s)) for s in specs]
    finished, pending = await asyncio.wait(tasks, timeout=PREP_BUDGET_S)
    for t in pending:  # out of time: start the class with what is ready
        t.cancel()
    if pending:
        log.warn("class-pictures-timeout", room=code, ready=len(pics), planned=len(specs))
    return {s.name: pics[s.name] for s in specs if s.name in pics}  # in step order


CHECKER = """You look at ONE picture made for a teacher who teaches Class 6 children (Hindi medium, rural Bihar) and judge it honestly. You are given the INTENT (the one thing a child should understand from it) and the description the picture was drawn from.
- `shows`: what the picture REALLY shows, in 2 plain English sentences (who or what, doing what, with what visible result). Describe what is there, not what was asked for.
- `communicates`: true only if a child who sees the picture without any words would understand the intent. Be strict: false if the objects just stand there, if the key action or effect cannot be seen, if the wrong things are shown, if there is any text, letters or numbers, or if hands, faces or objects are deformed.
- `problems`: short list of what is wrong (empty if communicates).
- `point_out`: 1-2 short things the teacher should draw the children's attention to, taken from what is really visible.
- `better_description`: only when communicates is false: a new description (English, at most 40 words) of ONE frozen moment in which the intent is clearly visible, fixing the problems. Otherwise empty."""


class PictureCheck(BaseModel):
    shows: str
    communicates: bool
    problems: list[str] = []
    point_out: str = ""
    better_description: str = ""


async def check_picture(client, path, spec: PicSpec, description: str) -> PictureCheck:
    img = types.Part.from_bytes(data=path.read_bytes(), mime_type="image/webp")
    r = await client.aio.models.generate_content(
        model=DEFAULT_TEXT_MODEL, contents=[img, f"INTENT: {spec.intent}\nDESCRIPTION IT WAS DRAWN FROM: {description}"],
        config=types.GenerateContentConfig(system_instruction=CHECKER, response_mime_type="application/json", response_schema=PictureCheck, temperature=0.1))
    return PictureCheck.model_validate(json.loads(r.text))


async def refine_pictures(code: str, specs: list[PicSpec], pics: dict[str, dict], progress) -> None:
    """A vision model looks at every drawn picture (what it really shows, does it carry its intent); one that does not is redrawn once from the checker's better description. Fills `shows`, `point_out`, `communicates` into `pics`."""
    if not pics:
        return
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    out_dir = WEB_PUBLIC / "chat" / f"class-{code}"
    by_name = {s.name: s for s in specs}

    async def one(name: str) -> None:
        spec, path = by_name[name], out_dir / f"{name}.webp"
        try:
            c = await check_picture(client, path, spec, pics[name]["description"])
            log.info("picture-check", room=code, name=name, communicates=c.communicates, shows=c.shows[:200], problems=c.problems, intent=spec.intent[:160])
            if not c.communicates and c.better_description:
                res = await picturegen.draw(c.better_description, path, LIVE_STYLE)
                log.info("picture-redraw", room=code, name=name, status=res.get("status"), description=c.better_description[:200])
                if res.get("status") == "ok":
                    pics[name]["description"] = c.better_description
                    c = await check_picture(client, path, spec, c.better_description)
                    log.info("picture-check", room=code, name=name, communicates=c.communicates, shows=c.shows[:200], problems=c.problems, after_redraw=True)
            pics[name].update({"shows": c.shows, "point_out": c.point_out, "communicates": c.communicates})
        except Exception as e:  # noqa: BLE001 - the unchecked picture is still usable: she gets the description it was drawn from
            log.warn("picture-check-failed", room=code, name=name, error=repr(e)[:200])
            pics[name].update({"shows": pics[name]["description"], "point_out": "", "communicates": True})

    await progress("चित्र जाँचे जा रहे हैं…")
    await asyncio.gather(*(one(n) for n in list(pics) if n in by_name))


def catalog_text(pics: dict[str, dict], figs: dict[str, dict]) -> str:
    """The teacher's catalog: what each picture / figure REALLY shows and what it is for (she cannot see them)."""
    lines = ["PICTURES (name — what it really shows | idea it carries | what to point out):"]
    for k, v in pics.items():
        lines.append(f"- {k} — {v.get('shows') or v.get('description') or v['caption']} | idea: {v.get('intent', '')} | point out: {v.get('point_out', '')}" if v.get("intent") else f"- {k} — {v['caption']} (for: {v['step']})")
    if not pics:
        lines.append("- none")
    lines.append("FIGURES (name — what it contains | idea it carries):")
    for k, v in figs.items():
        lines.append(f"- {k} — {v.get('description', v['caption'])} | idea: {v.get('intent', '')}")
    if not figs:
        lines.append("- none")
    return "\n".join(lines)


async def prepare_topic(code: str, topic: str, progress) -> dict:
    """Notes + the kit for a topic. Returns {"refused": reason} or {"notes", "steps", "pictures": {name: {src, caption, step, intent, shows, point_out}}, "figures": {name: {html, caption, step, intent, description}}, "catalog": text}."""
    t0 = time.time()
    await progress("टीचर क्लास की तैयारी कर रही हैं…")
    r = await prep.prepare([types.Part(text=f"The children want to learn this: {topic}")], prep.recorded_lessons(), None, f"class-{code}")
    if r["refused"]:
        return {"refused": r["refused"]}
    notes = r["notes"]
    try:
        kit = await plan_kit(notes)
    except Exception as e:  # noqa: BLE001 - a class without pictures is better than no class
        log.error("kit-plan-failed", room=code, error=repr(e)[:300])
        kit = KitPlan(steps=[], pictures=[], figures=[])
    log.info("picture-plan", room=code, steps=kit.steps, pictures=[(s.name, s.step, s.intent, s.description) for s in kit.pictures], figures=[(s.name, s.step, s.intent, s.description) for s in kit.figures])
    pics, figs = await asyncio.gather(make_pictures(code, kit.pictures, progress), figures.make_figures(code, kit.figures, progress))
    await refine_pictures(code, kit.pictures, pics, progress)
    for name in [k for k, v in pics.items() if v.get("communicates") is False]:  # still wrong after one redraw: do not offer the teacher a picture that tells a different story
        log.warn("picture-dropped", room=code, name=name, shows=pics[name].get("shows", "")[:200])
        pics.pop(name)
    # pictures of related recorded lessons are available too
    for name, src in prep.pictures_of(r["related"]).items():
        pics.setdefault(name, {"src": src, "caption": "", "step": "related recorded lesson"})
    log.info("kit-ready", room=code, seconds=round(time.time() - t0), pictures=len(pics), figures=len(figs), dropped=len([s for s in kit.pictures if s.name not in pics]))
    return {"notes": notes, "steps": kit.steps, "pictures": pics, "figures": figs, "catalog": catalog_text(pics, figs)}
