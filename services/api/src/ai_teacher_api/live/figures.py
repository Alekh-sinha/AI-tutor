"""HTML FIGURES of a live class: labelled diagrams, tables, number lines, before/after pairs, small animations that a photo cannot show. Written in the PLANNING stage by a text model (never by the live
voice model while she speaks), checked in code, and pulled by the teacher with show_figure. The browser shows them inside a Shadow DOM after a second sanitising pass (apps/web/src/live/Figure.tsx).
Spike 2026-10-16 (tests/e2e/html_spike_*.py): 5 of 6 figures looked right at 360 px (arrows, tables, scales, before/after, CSS animation); objects drawn from emoji look crude, so objects stay photos."""

import asyncio
import re
import time
from html.parser import HTMLParser

from google import genai
from google.genai import types

from ai_teacher_api.safety import policy
from ai_teacher_api.common import logsetup
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION

log = logsetup.get("live")
MAX_CHARS = 7000
TRIES = 2
ALLOWED_TAGS = {"div", "span", "p", "b", "i", "strong", "em", "br", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "style", "h3", "h4", "small", "svg", "path", "line", "polyline", "circle", "rect", "g"}
ALLOWED_ATTRS = {"class", "style", "viewbox", "d", "points", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "width", "height", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "transform", "colspan", "rowspan", "xmlns", "preserveaspectratio", "rx", "ry", "opacity"}
BAD_TEXT = re.compile(r"url\s*\(|@import|javascript:|expression\s*\(|<!--|behavior\s*:|-moz-binding|position\s*:\s*fixed", re.I)

WRITER = """You draw ONE classroom figure for a Hindi class (Class 6, rural Bihar) as an HTML fragment that will be shown on a white board on a phone (container width 300-380 px, height at most 280 px).
Rules: layout with flexbox/grid and percentages only, no pixel coordinates, no position:absolute except tiny offsets; no <script>, no external files, no <img>, no url(); inline style attributes or ONE <style> block scoped under the class .fig.
Text in Hindi (Devanagari), font-size at least 15px, short words. Arrows with characters (→ ← ↑ ↓ ⇄) or CSS borders; emoji allowed for small icons. Soft colours on white: dark ink #1f2937, accent #0f766e, warm #c2410c, light fills. Rounded boxes, clear spacing. Everything must fit without scrolling.
Never draw an object or a living thing from emoji and blocks (it looks crude): show objects as a labelled box with ONE emoji, or leave them to the photos. A small CSS @keyframes animation (translateX in %, opacity) is welcome when the idea is motion.
Output ONLY the HTML fragment, starting with <div class="fig">. No markdown fences."""
WRITER += "\n\n" + policy.POLICY


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.open: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.problems.append(f"tag <{tag}> is not allowed")
        for k, v in attrs:
            if k.lower() not in ALLOWED_ATTRS:
                self.problems.append(f"attribute {k} on <{tag}> is not allowed")
            elif v and BAD_TEXT.search(v):
                self.problems.append(f"unsafe value in {k}")
        if tag not in ("br", "path", "line", "circle", "rect", "polyline"):
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in self.open:
            while self.open and self.open.pop() != tag:
                pass

    def handle_data(self, data):
        if BAD_TEXT.search(data):  # inside <style>: url(), @import, position:fixed
            self.problems.append("unsafe CSS")


def check_html(html: str) -> list[str]:
    """Problems that make a figure unusable (empty list = good). Rejects instead of repairing: the writer is asked again."""
    html = (html or "").strip()
    if not html.startswith('<div class="fig"'):
        return ['must start with <div class="fig">']
    if len(html) > MAX_CHARS:
        return [f"too long ({len(html)} characters, at most {MAX_CHARS})"]
    c = _Checker()
    c.feed(html)
    c.close()
    if not re.search(r"[ऀ-ॿ]", html):
        c.problems.append("no Hindi text")
    return sorted(set(c.problems))[:6]


async def write_figure(client, description: str) -> tuple[str, list[str]]:
    """Write one figure; on a failed check ask again with the problems (TRIES attempts). Returns (html, problems_left)."""
    prompt, html, problems = description, "", ["not written"]
    for _ in range(TRIES):
        r = await client.aio.models.generate_content(model=DEFAULT_TEXT_MODEL, contents=prompt, config=types.GenerateContentConfig(system_instruction=WRITER, temperature=0.4))
        html = (r.text or "").strip().removeprefix("```html").removesuffix("```").strip()
        problems = check_html(html)
        if not problems:
            return html, []
        prompt = f"{description}\n\nYour previous figure was rejected: {'; '.join(problems)}. Write it again, fixing exactly that."
    return html, problems


async def make_figures(code: str, specs, progress) -> dict[str, dict]:
    """Write all planned figures in parallel (text model: no image quota). Returns {name: {"html", "caption", "step"}} of those that passed the checks."""
    if not specs:
        return {}
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    out: dict[str, dict] = {}
    done = 0

    async def one(s) -> None:
        nonlocal done
        t0 = time.time()
        try:
            html, problems = await write_figure(client, s.description)
        except Exception as e:  # noqa: BLE001 - one failed figure must not stop the class
            html, problems = "", [repr(e)[:200]]
        log.info("class-figure", room=code, name=s.name, ok=not problems, problems=problems, chars=len(html), seconds=round(time.time() - t0, 1), description=s.description[:160])
        done += 1
        if not problems:
            out[s.name] = {"html": html, "caption": s.caption, "step": s.step, "intent": s.intent, "description": s.description}
        await progress(f"चित्र और आकृतियाँ बन रही हैं… {done}/{len(specs)}")

    await asyncio.gather(*(one(s) for s in specs))
    return {s.name: out[s.name] for s in specs if s.name in out}
