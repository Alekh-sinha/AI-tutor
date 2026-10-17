"""The teacher's whole journey as an approved user on the deployed (or local AUTH_MODE=on) server: upload a chapter PDF -> plan -> generate a lesson (20-40 min) -> review ->
publish -> edit the video as a hidden draft -> publish the draft; credit is charged on the way. Needs AUTH_DEV_LOGIN=1 on the server.
Run (outside services/api): AUTH_BEARER=$(gcloud auth print-identity-token) BASE=https://... uv run --offline --with playwright==1.63.0 python -u tests/e2e/access_teacher.py <dir> [pdf]"""
import glob, json, os, sys, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

BASE = os.environ["BASE"]; OUT = sys.argv[1]; PDF = sys.argv[2] if len(sys.argv) > 2 else "docs/source/chapter.pdf"
H = {"Authorization": "Bearer " + os.environ["AUTH_BEARER"]} if os.environ.get("AUTH_BEARER") else {}
ADMIN, USER = "alekh.sinha09@gmail.com", f"maker{int(time.time()) % 100000}@example.com"
CHROME = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
res = []


def check(n, ok, d=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n, d, flush=True)


def wait_job(api, jid, label, limit=3000):
    t0, last = time.time(), ""
    while time.time() - t0 < limit:
        j = api.get(f"{BASE}/api/teacher/jobs/{jid}").json()
        if j["stage"] != last:
            last = j["stage"]; print(f"   [{label}] {round(time.time() - t0)}s stage: {last}", flush=True)
        if j["status"] != "running":
            return j
        time.sleep(15)
    return {"status": "timeout", "error": "timeout"}


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
    adm = b.new_context(extra_http_headers=H); adm.request.get(f"{BASE}/api/auth/dev", params={"email": ADMIN})
    ctx = b.new_context(viewport={"width": 1300, "height": 900}, extra_http_headers=H); ctx.request.get(f"{BASE}/api/auth/dev", params={"email": USER})
    api = ctx.request
    adm.request.post(f"{BASE}/api/admin/users/{quote(USER)}/grant", data={"usd": 10})
    adm.request.post(f"{BASE}/api/admin/users/{quote(USER)}/cap", data={"usd": 10})
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))

    # 1. upload + plan
    r = api.post(f"{BASE}/api/teacher/chapters", multipart={"chapter": "mine", "book": "NCERT Class 6 Science, Ch. 6 (test copy)", "pdf": {"name": "ch.pdf", "mimeType": "application/pdf", "buffer": open(PDF, "rb").read()}})
    check("upload accepted", r.ok, r.text()[:120])
    job = wait_job(api, r.json()["id"], "plan", 600)
    check("the chapter was parsed and planned", job["status"] == "done", str(job.get("result") or job.get("error"))[:120])
    chapters = api.get(f"{BASE}/api/teacher/chapters").json()
    mine = [c for c in chapters if c["id"].startswith("u") and "-" in c["id"]]
    check("the user sees only their own chapter, with the owner prefix", len(chapters) == 1 and len(mine) == 1, str([c["id"] for c in chapters]))
    cid = mine[0]["id"]; lesson = mine[0]["lessons"][0]["id"]

    # 2. generate (long)
    t0 = time.time()
    g = api.post(f"{BASE}/api/teacher/lesson/{lesson}/generate?chapter={cid}")
    check("generation started", g.ok, g.text()[:150])
    job = wait_job(api, g.json()["id"], "generate", 3300)
    check("the lesson was generated", job["status"] == "done", f"{round((time.time() - t0) / 60)} min; {str(job.get('result') or job.get('error'))[:200]}")
    info = adm.request.get(f"{BASE}/api/admin/users/{quote(USER)}").json()
    kinds = {}
    for x in info["ledger"]:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + x["usd"]
    print("COST by kind:", {k: round(v, 2) for k, v in kinds.items()}, "| spent:", info["user"]["spent_usd"], flush=True)
    pg.goto(f"{BASE}/teacher?chapter={cid}"); pg.wait_for_timeout(2500); pg.screenshot(path=f"{OUT}/t1-chapter.png")
    pub0 = next(l for c in api.get(f"{BASE}/api/teacher/chapters").json() for l in c["lessons"] if l["id"] == lesson)
    check("the lesson is In review (not published)", pub0["has_lecture"] and not pub0["live"])

    # 3. publish
    v = api.get(f"{BASE}/api/teacher/lesson/{lesson}?chapter={cid}").json()
    print("   code checks left:", v["checks"][:3])
    pid = v["public_id"]
    api.post(f"{BASE}/api/teacher/lesson/{lesson}/publish?chapter={cid}", data={"approved_by_teacher": True})
    ok = False
    for _ in range(120):
        time.sleep(10)
        s = api.get(f"{BASE}/api/teacher/lesson/{lesson}/publish-status?chapter={cid}").json()
        if s["status"] in ("done", "failed"):
            ok = s["status"] == "done"; print("   publish:", s); break
    pubs = next(l for c in api.get(f"{BASE}/api/teacher/chapters").json() for l in c["lessons"] if l["id"] == lesson)
    check("the lesson is published (live, v1)", pubs["live"] and pubs["version"] == 1, f"ok={ok} {pubs}")
    live1 = api.get(f"{BASE}/lessons/{pid}.json").text()

    # 4. edit the video of the LIVE lesson: a hidden draft, students keep v1
    vid = api.get(f"{BASE}/api/teacher/lesson/{lesson}/video?chapter={cid}").json()
    line = next(l for l in vid["lines"] if len(l["text"]) > 30)
    ev = api.post(f"{BASE}/api/teacher/lesson/{lesson}/video/edit?chapter={cid}", data={"instruction": f"line {line['i']} को थोड़ा और आसान शब्दों में बोलो", "selection": f"line:{line['i']}"})
    prop = None
    for chunk in ev.text().split("\n\n"):
        if chunk.startswith("data: "):
            e = json.loads(chunk[6:])
            if e.get("type") == "proposal":
                prop = e
    check("the video editor proposed a change", prop is not None)
    if prop:
        acc = api.post(f"{BASE}/api/teacher/lesson/{lesson}/video/accept/{prop['id']}?chapter={cid}")
        j = wait_job(api, acc.json()["id"], "video rebuild", 600)
        check("the draft video was rebuilt", j["status"] == "done", str(j.get("error")))
        live_now = api.get(f"{BASE}/api/teacher/lesson/{lesson}/video?chapter={cid}").json()["publish"]
        check("a draft exists and students still see v1", live_now["video_changed"] and live_now["draft_ready"] and api.get(f"{BASE}/lessons/{pid}.json").text() == live1, str(live_now))
        pg.goto(f"{BASE}/teacher?chapter={cid}"); pg.wait_for_timeout(2500); pg.screenshot(path=f"{OUT}/t2-draft.png")
        d = api.post(f"{BASE}/api/teacher/lesson/{lesson}/video/publish-draft?chapter={cid}")
        check("the draft was published as v2", d.ok and d.json().get("version") == 2, d.text()[:100])
        check("students now see the changed video", api.get(f"{BASE}/lessons/{pid}.json").text() != live1)
    check("no JavaScript errors", not errs, str(errs[:3]))
    b.close()
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
