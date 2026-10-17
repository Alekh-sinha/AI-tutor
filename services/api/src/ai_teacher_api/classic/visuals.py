"""Output of the visual agent. Diagrams are drawn WITHOUT text; words travel as separate labels that the
player renders with a real font (editable by teachers, translatable, no font problems inside images)."""

import re
import xml.etree.ElementTree as ET
from typing import Literal

from pydantic import BaseModel, Field

SIZES = {"sm": 18.0, "md": 22.0, "lg": 28.0}  # viewBox units


class LabelSpec(BaseModel):
    text: str = Field(description="1-3 words in the lesson language, spelled exactly as in the description")
    x: float = Field(description="Centre x in viewBox units (0-480)")
    y: float = Field(description="Centre y in viewBox units (0-300)")
    size: Literal["sm", "md", "lg"] = "md"
    color: str | None = Field(None, description="hex colour, default dark ink")


class SvgAsset(BaseModel):
    cue_id: str = Field(description="id of the svg cue this drawing is for")
    svg: str = Field(description="complete <svg> markup with NO <text> elements, that passed validate_svg")
    labels: list[LabelSpec] = Field(description="every word shown on the diagram")


class LessonVisuals(BaseModel):
    lesson_id: str
    assets: list[SvgAsset] = Field(default=[], description="finished svg diagrams")
    images: list[str] = Field(default=[], description="cue ids whose illustration generate_illustration returned ok for")


BAD_TAGS = {"script", "foreignobject", "image", "iframe", "use", "text", "tspan"}
VB = re.compile(r"[\s,]+")


def viewbox(svg: str) -> tuple[float, float]:
    root = ET.fromstring(svg)
    x, y, w, h = (float(v) for v in VB.split(root.attrib["viewBox"].strip()))
    return w, h


def label_box(l: LabelSpec) -> tuple[float, float, float, float]:
    """Rough extent of a label (Devanagari glyphs are ~0.55 em wide): left, top, right, bottom."""
    size = SIZES[l.size]
    w = max(len(l.text), 1) * size * 0.55
    return l.x - w / 2, l.y - size * 0.6, l.x + w / 2, l.y + size * 0.6


def check_svg(svg: str, labels: list[LabelSpec] | None = None) -> list[str]:
    """Return a list of problems; empty means the diagram is safe and usable."""
    labels = labels or []
    problems = []
    if len(svg.encode()) > 8192:
        problems.append("larger than 8 KB: simplify")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    if not root.tag.endswith("svg"):
        problems.append("root element must be <svg>")
    if "viewBox" not in root.attrib:
        return problems + ['missing viewBox (use viewBox="0 0 480 300")']
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag == "text" or tag == "tspan":
            problems.append("<text> is not allowed: put every word in `labels` instead")
        elif tag in BAD_TAGS:
            problems.append(f"forbidden element <{tag}>")
        for attr in el.attrib:
            if attr.lower().startswith("on") or (attr.endswith("href") and not el.attrib[attr].startswith("#")):
                problems.append(f"forbidden attribute {attr}")
    try:
        w, h = viewbox(svg)
    except (ValueError, KeyError):
        return problems + ["viewBox must be four numbers"]
    if not labels:
        problems.append("no labels: a teaching diagram needs its key words as labels")
    for l in labels:
        x0, y0, x1, y1 = label_box(l)
        if not (l.text.strip() and len(l.text) <= 40):
            problems.append(f"label '{l.text[:15]}' must be 1-40 characters")
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            problems.append(f"label '{l.text}' runs outside the picture: move it inward or shorten it")
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            ax0, ay0, ax1, ay1 = label_box(a)
            bx0, by0, bx1, by1 = label_box(b)
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                problems.append(f"labels '{a.text}' and '{b.text}' overlap: move one")
    return problems


def validate_svg(svg: str, labels: list[LabelSpec]) -> dict:
    """Check a diagram and its labels before submitting.

    Args:
        svg: the complete SVG markup (no <text> elements).
        labels: every word on the diagram, with centre position in viewBox units.

    Returns:
        {"ok": bool, "problems": [...]}: fix every problem and call again until ok is true.
    """
    problems = check_svg(svg, labels)
    return {"ok": not problems, "problems": problems}


def to_player_labels(svg: str, labels: list[LabelSpec]) -> list[dict]:
    """Convert viewBox-unit labels to the player's percentage-based Label dicts."""
    w, h = viewbox(svg)
    return [
        {"text": l.text, "x": round(l.x / w * 100, 2), "y": round(l.y / h * 100, 2),
         "size": round(SIZES[l.size] / w * 100, 2), "color": l.color, "bold": False}
        for l in labels
    ]


def preview_svg(svg: str, labels: list[LabelSpec]) -> str:
    """For human review only: bake labels into the SVG as <text> so a rasteriser can show them."""
    texts = "".join(
        f'<text x="{l.x}" y="{l.y}" font-size="{SIZES[l.size]}" text-anchor="middle" dominant-baseline="central" '
        f'font-family="Noto Sans Devanagari" fill="{l.color or "#222"}">{l.text}</text>'
        for l in labels
    )
    return svg.replace("</svg>", texts + "</svg>")
