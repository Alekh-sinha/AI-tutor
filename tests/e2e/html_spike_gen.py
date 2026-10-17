"""SPIKE: can a text model write classroom diagrams as plain HTML that look right at phone width? Writes <out>/<name>.html fragments; html_spike_shot.py renders them."""
import asyncio, sys, time, pathlib
from google import genai
from google.genai import types
from ai_teacher_api.common.settings import DEFAULT_TEXT_MODEL, PROJECT, TEXT_LOCATION

WRITER = """You draw ONE classroom figure for a Hindi class (Class 6, rural Bihar) as an HTML fragment that will be shown on a white board on a phone (container width 300-380 px, height at most 280 px).
Rules: layout with flexbox/grid and percentages only, no pixel coordinates, no position:absolute except tiny offsets; no <script>, no external files, no <img>, no <svg> unless a tiny arrow; inline style attributes or ONE <style> block scoped under the class .fig.
Text in Hindi (Devanagari), font-size at least 15px, short words. Arrows with characters (→ ← ↑ ↓ ⇄) or CSS borders; emoji allowed for objects. Soft colours on white: dark ink #1f2937, accent #0f766e, warm #c2410c, light fills. Rounded boxes, clear spacing. Everything must fit without scrolling.
Output ONLY the HTML fragment, starting with <div class="fig">. No markdown fences."""

CASES = {
 "friction_push": "A cupboard (box labelled अलमारी) on a floor line. A long arrow above pointing right labelled 'धक्का'. A shorter arrow under it pointing left labelled 'घर्षण बल'. The floor is a thick line labelled 'फर्श'.",
 "surface_table": "A table with 3 rows comparing surfaces and friction: चिकना फर्श (कम), सीमेंट का आँगन (मध्यम), खुरदरी ईंट (ज़्यादा). Add a small bar made of coloured blocks showing how much friction (1, 2, 3 blocks).",
 "number_line": "A number line from 0 to 100 for temperature in °C with marks at 0 (बर्फ़ पिघलती है) and 100 (पानी उबलता है) and a marker at 30 (आज की गर्मी).",
 "labelled_parts": "A plant drawn with emoji/blocks stacked vertically: पत्ती at top, तना in the middle, जड़ at the bottom (under a brown ground band), each with a label and an arrow pointing at it from the right side.",
 "before_after": "Two side-by-side cards 'पहले' and 'बाद में'. Left: a door hinge 🚪 with label 'जंग लगा कब्ज़ा — चर्र-चर्र, घर्षण ज़्यादा'. Right: the hinge with oil 🛢️ label 'तेल लगा — चिकना, घर्षण कम'. A big arrow between them.",
 "anim_push": "A box 📦 sliding slowly right and left on a floor line with a CSS @keyframes animation (translateX in %), a push arrow → above it and a friction arrow ← below it that pulses (opacity). Labels 'धक्का' and 'घर्षण'. Floor line labelled 'खुरदरी ज़मीन'.",
}

async def main(out):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    client = genai.Client(vertexai=True, project=PROJECT, location=TEXT_LOCATION)
    async def one(name, desc):
        t = time.time()
        r = await client.aio.models.generate_content(model=DEFAULT_TEXT_MODEL, contents=desc,
            config=types.GenerateContentConfig(system_instruction=WRITER, temperature=0.4))
        html = (r.text or "").strip().removeprefix("```html").removesuffix("```").strip()
        (out / f"{name}.html").write_text(html)
        print(f"{name}: {time.time()-t:.1f}s {len(html)} chars", flush=True)
    await asyncio.gather(*(one(n, d) for n, d in CASES.items()))

asyncio.run(main(sys.argv[1]))
