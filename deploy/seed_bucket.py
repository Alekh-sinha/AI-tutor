"""Build the starting content of the data bucket from the local working folder: the first book (ch6) with its four v2 lessons (editable by the admin) and the two FREE lessons.
Only what the deployed service needs: no experiments, old classic lessons, test chapters, logs. Output: a staging folder that mirrors the bucket layout (data/..., public/...).
Run: cd services/api && uv run python ../../deploy/seed_bucket.py <staging-dir>  then  gcloud storage rsync -r <staging-dir> gs://BUCKET"""
import json
import shutil
import sys
import time
from pathlib import Path

from ai_teacher_api.teacher import publishing

ROOT = Path(__file__).resolve().parents[1]
DATA, PUB = ROOT / "data", ROOT / "apps/web/public"
OUT = Path(sys.argv[1])
FREE = ["lesson-1-v2", "lesson-3-v2"]
LESSONS = [f"lesson-{n}" for n in (1, 2, 3, 4)]
SKIP_IN_LECTURE = ("audit-", "image-attempts", "improve-", "baseline", "versions", "proposals")

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "data/ch6/illustrated").mkdir(parents=True)
for sub in ("lessons", "audio", "img"):
    (OUT / "public" / sub).mkdir(parents=True)

ch = DATA / "ch6"
for f in ("chapter.json", "plan.json"):
    shutil.copy(ch / f, OUT / "data/ch6" / f)
for l in LESSONS:
    pid = f"{l}-v2"
    for name in (f"brief-{l}.json", f"brief-{l}.md", f"directed-{pid}.json", f"direct-{pid}.json"):
        if (ch / name).exists():
            shutil.copy(ch / name, OUT / "data/ch6" / name)
    src = ch / "illustrated" / f"{l}-final"
    dst = OUT / "data/ch6/illustrated" / f"{l}-final"
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if f.is_file() and not f.name.startswith(SKIP_IN_LECTURE) and (f.suffix in (".webp", ".md")):
            shutil.copy(f, dst / f.name)
    shutil.copy(PUB / "lessons" / f"{pid}.json", OUT / "public/lessons" / f"{pid}.json")
    shutil.copy(PUB / "audio" / f"{pid}.mp3", OUT / "public/audio" / f"{pid}.mp3")
    for f in (PUB / "img").glob(f"{pid}-*.webp"):
        shutil.copy(f, OUT / "public/img" / f.name)

# index: the four v2 lessons; the two free ones are published (with their publish state, so later edits become drafts)
old = json.loads((PUB / "lessons/index.json").read_text())
index = []
for e in old:
    if e["id"] in [f"{l}-v2" for l in LESSONS]:
        index.append({**e, "status": "published" if e["id"] in FREE else "draft"})
(OUT / "public/lessons/index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
(OUT / "data/public-lessons.json").write_text(json.dumps(FREE))
for pid in FREE:
    l = pid.removesuffix("-v2")
    md = (ch / "illustrated" / f"{l}-final" / "lecture.md").read_text()
    script = (ch / f"directed-{pid}.json").read_text()
    st = {"version": 1, "lecture_sha": publishing.sha(md), "script_sha": publishing.sha(script), "at": time.time()}
    (OUT / f"data/ch6/publish-state-{pid}.json").write_text(json.dumps(st))
    (OUT / f"data/ch6/directed-live-{pid}.json").write_text(script)

total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
print(f"seed ready: {sum(1 for f in OUT.rglob('*') if f.is_file())} files, {total / 1e6:.1f} MB at {OUT}")
