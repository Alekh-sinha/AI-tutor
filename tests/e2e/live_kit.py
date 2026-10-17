"""Planning stage alone (no server): notes -> kit plan -> pictures + figures -> vision check. Prints what the planner wanted and what the vision check says each picture REALLY shows; writes figures to <out>/*.html and the pictures to <out>/*.webp
(for html_spike_shot.py and for looking at them). Run: cd services/api && uv run python ../../tests/e2e/live_kit.py <topic> <out_dir> <room_code>"""
import asyncio, json, pathlib, shutil, sys, time
from ai_teacher_api.live import prepare
from ai_teacher_api.common.settings import WEB_PUBLIC

async def main(topic, out, code):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    async def progress(t): print(f"[{time.time()-t0:5.0f}s] {t}", flush=True)
    r = await prepare.prepare_topic(code, topic, progress)
    print(f"DONE in {time.time()-t0:.0f}s")
    print("STEPS:", r.get("steps"))
    for k, v in r["pictures"].items():
        print(f"\nPICTURE {k} [{v['step']}]\n  intent : {v.get('intent')}\n  drawn from: {v.get('description')}\n  really shows: {v.get('shows')}\n  communicates: {v.get('communicates')}  point out: {v.get('point_out')}")
        src = WEB_PUBLIC / v["src"].lstrip("/")
        if src.exists(): shutil.copy(src, out / f"{k}.webp")
    for k, v in r["figures"].items():
        print(f"\nFIGURE {k} [{v['step']}]\n  intent: {v.get('intent')}\n  spec  : {v.get('description')}")
        (out / f"{k}.html").write_text(v["html"])
    (out / "catalog.txt").write_text(r["catalog"])
asyncio.run(main(*sys.argv[1:4]))
