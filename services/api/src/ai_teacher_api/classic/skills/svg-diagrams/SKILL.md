---
name: svg-diagrams
description: How to draw clear, labelled teaching diagrams as SVG for a white classroom board read by village children on small phones.
---

# SVG teaching diagrams

## When to draw an SVG at all
Only for a simple, big, friendly diagram: a two-sided comparison with a tick and a cross, or an object with 3-5 labelled parts.
Never a table, a flowchart or a grid of boxes: those feel like a textbook. Prefer one large central drawing.

## Canvas
- `viewBox="0 0 480 300"`, no fixed width/height, transparent background (the board is white).
- Everything must stay readable on a 5-inch phone: text >= 20 units, strokes >= 3, generous spacing.
  Maximum 6 labelled things per diagram. If the description has more, keep the essential ones.

## Style
- Flat, friendly, hand-drawn feel: rounded shapes (`rx`), thick outlines (#333), soft fills.
- Palette: clay #c8693a, steel/metal #8a97a6, paper #f2e6c8, green #3a9a3a, water #4aa3df, sun #f5b301, alert red #c0392b, ink #222.
- Draw recognisable objects from simple shapes (a kulhad is a trapezoid cup, a glass is a tall rect, a cloth bag is a wavy sack).
- Use arrows (`<path>` with a marker or small triangle) to show relationships, and a tick (green) / cross (red) for yes/no.

## Words go in `labels`, never in the SVG
- The SVG must contain NO `<text>`. The player draws the words itself with a proper Hindi font on top of your picture.
- Each label: `text` (1-3 words in the lesson language, spelled exactly as in the description), `x`,`y` = centre of the
  label in viewBox units (0-480, 0-300), `size` sm/md/lg (about 18/22/28 units), optional `color` hex.
- Place a label under or beside the object it names, clear of other labels. A label about 22 units tall and
  ~12 units wide per character must fit inside the picture.
- Leave empty space in the drawing where each label will go (e.g. a blank 60-unit strip under each object).

## Safety and size
- Pure SVG only: no `<script>`, `<foreignObject>`, event attributes, external links or images.
- Under 8 KB. Call `validate_svg(svg, labels)` on every diagram, fix every problem it reports, and call it again until it passes.
