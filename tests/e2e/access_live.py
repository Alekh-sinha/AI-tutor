"""A live class paid by a signed-in, approved user: metering while it runs, and the class ending kindly when the day's limit is reached.
Server (production-style): AUTH_MODE=on AUTH_DEV_LOGIN=1 STORE=memory uvicorn ai_teacher_api.server:root --port 8002
Run (outside services/api): BASE=http://localhost:8002 uv run --offline --with playwright==1.63.0 python -u tests/e2e/access_live.py <dir> [topic]"""
import glob, os, sys, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://localhost:8002"); OUT = sys.argv[1]; TOPIC = sys.argv[2] if len(sys.argv) > 2 else "पानी में नमक क्यों घुल जाता है?"
ADMIN, USER = "alekh.sinha09@gmail.com", "host.teacher@example.com"
CHROME = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
H = {"Authorization": "Bearer " + os.environ["AUTH_BEARER"]} if os.environ.get("AUTH_BEARER") else {}
res = []


def check(n, ok, d=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n, d, flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    adm = b.new_context(extra_http_headers=H); adm.request.get(f"{BASE}/api/auth/dev", params={"email": ADMIN})
    ctx = b.new_context(viewport={"width": 420, "height": 860}, permissions=["microphone"], extra_http_headers=H); ctx.request.get(f"{BASE}/api/auth/dev", params={"email": USER})
    adm.request.post(f"{BASE}/api/admin/users/{quote(USER)}/grant", data={"usd": 5})
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{BASE}/live"); pg.wait_for_timeout(1500)
    pg.fill("input[placeholder^='What should']", TOPIC); pg.click("button[aria-label='Start the class']")
    pg.wait_for_selector(".lr-code b", timeout=20000)
    check("host got a class code", len(pg.inner_text(".lr-code b")) == 5)
    pg.screenshot(path=f"{OUT}/live-0-lobby.png")
    pg.click("text=कक्षा शुरू करें")
    t0 = time.time(); first = None
    while time.time() - t0 < 480:
        if pg.query_selector(".lr-board .el") and first is None:
            first = time.time(); break
        time.sleep(1)
    check("the class started after planning (first screen on the board)", first is not None, f"{round(time.time() - t0)}s")
    pg.screenshot(path=f"{OUT}/live-1-first-screen.png")
    time.sleep(45)  # let her teach for a while
    info = adm.request.get(f"{BASE}/api/admin/users/{quote(USER)}").json()
    kinds = {}
    for r in info["ledger"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["usd"]
    print("ledger by kind:", {k: round(v, 3) for k, v in kinds.items()}, "| spent", info["user"]["spent_usd"], "| live minutes", info["user"]["counters"].get("live_seconds", 0) / 60)
    check("the host was charged for the planning (model + image lines in the ledger)", kinds.get("model", 0) > 0 and "grant" in kinds)
    check("the host was charged for the live session while it runs", kinds.get("live", 0) > 0, f"{kinds.get('live', 0):.3f}")
    # the day's limit is reached mid-class: the class ends with a clear message
    adm.request.post(f"{BASE}/api/admin/users/{quote(USER)}/cap", data={"usd": 0.01})
    ended = ""
    for _ in range(90):
        time.sleep(1)
        if pg.query_selector(".lr-center h2"):
            ended = pg.inner_text(".lr-center h2"); break
    check("the class ended kindly when the limit was reached", "सीमा" in ended or "क्रेडिट" in ended, ended[:80])
    pg.screenshot(path=f"{OUT}/live-2-ended.png")
    check("no JavaScript errors", not errs, str(errs[:3]))
    b.close()
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
