"""Step 1 of the lesson pipeline: PDF -> chapter.json (page-tagged text), plain code, no LLM.

Heading levels from the PDF are unreliable (a section can be mis-leveled or lost), so we keep
the full text per page plus the headings/activities we can detect, and let the planner agent
decide the section structure. Page numbers are what make per-line source references possible.
"""

import json
import re
import sys
from pathlib import Path

from liteparse import LiteParse
from pydantic import BaseModel


class Heading(BaseModel):
    page: int
    level: int
    text: str


class Activity(BaseModel):
    id: str
    page: int
    title: str


class Page(BaseModel):
    page: int
    text: str


class Chapter(BaseModel):
    book: str
    title: str
    source_pdf: str
    pages: list[Page]
    headings: list[Heading]
    activities: list[Activity]


PAGE_BREAK = re.compile(r"\n-----\n")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
ACTIVITY = re.compile(r"Activity\s+(\d+\.\d+)\s*:?\s*(.*)")
IMAGE = re.compile(r"^!\[\]\([^)]*\)\s*$", re.M)


def parse_chapter(pdf: Path, book: str) -> Chapter:
    md = LiteParse(output_format="markdown", image_mode="placeholder", ocr_enabled=False, quiet=True).parse(str(pdf))
    pages = [IMAGE.sub("", t).strip() for t in PAGE_BREAK.split(md.text)]
    if len(pages) != md.total_pages:
        raise ValueError(f"page split mismatch: {len(pages)} chunks vs {md.total_pages} pages")
    headings, activities = [], []
    for n, text in enumerate(pages, start=1):
        for line in text.splitlines():
            if m := HEADING.match(line):
                headings.append(Heading(page=n, level=len(m[1]), text=m[2]))
            # activity titles are not always headings, so look at every line (first mention wins)
            if (a := ACTIVITY.search(line)) and a[1] not in {x.id for x in activities}:
                activities.append(Activity(id=a[1], page=n, title=a[2].strip().strip("*#.| ")))
    title = next((h.text for h in headings if h.level == 1), pdf.stem)
    return Chapter(
        book=book,
        title=title,
        source_pdf=str(pdf),
        pages=[Page(page=n, text=t) for n, t in enumerate(pages, start=1)],
        headings=headings,
        activities=activities,
    )


def main() -> None:
    pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    ch = parse_chapter(pdf, book="NCERT Class 6 Science, Ch. 6")
    out.write_text(json.dumps(ch.model_dump(), ensure_ascii=False, indent=2) + "\n")
    print(f"{ch.title}: {len(ch.pages)} pages, {len(ch.headings)} headings, activities {[a.id for a in ch.activities]}")


if __name__ == "__main__":
    main()
