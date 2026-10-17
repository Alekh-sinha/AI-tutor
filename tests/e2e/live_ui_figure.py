"""Browser check that a planner-made HTML figure appears on the live board (topic class: planning ~1 min, then she calls show_figure). Needs API + vite (WEB_PORT). Saves live-figure.png.
Run (outside services/api): WEB_PORT=5198 uv run --offline --with playwright==1.63.0 python -u tests/e2e/live_ui_figure.py <dir>"""
import glob, os, sys, time
from playwright.sync_api import sync_playwright
WEB = f"http://localhost:{os.environ.get('WEB_PORT', '5199')}"; OUT = sys.argv[1] if len(sys.argv) > 1 else "."
CHROME = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"])
    pg = b.new_context(viewport={"width": 420, "height": 860}).new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{WEB}/?room=new"); pg.fill(".lr-input", "गुरुजी"); pg.click("text=नई कक्षा बनाएँ"); pg.wait_for_selector(".lr-code b")
    pg.fill("input[placeholder^='आज क्या']", "घर्षण (friction)"); pg.click("text=कक्षा शुरू करें")
    t0 = time.time(); ok = False
    while time.time() - t0 < 420:
        host = pg.query_selector(".lr-board .el-figure .figure-host")
        if host and pg.evaluate("h => !!h.shadowRoot && h.shadowRoot.querySelectorAll('div,span,p').length > 3", host): ok = True; break
        time.sleep(1)
    time.sleep(2); pg.screenshot(path=f"{OUT}/live-figure.png")
    print("figure on the board with content in its shadow DOM:", ok, "| JS errors:", errs, "| elements:", len(pg.query_selector_all('.lr-board .el')))
    b.close()
