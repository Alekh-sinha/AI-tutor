"""End-to-end smoke test in a real (headless) browser. Needs the API on :8000 and the web dev server on $WEB_PORT (default 5199).
Run (from any directory outside services/api, so the project venv is not touched): uv run --offline --with playwright==1.63.0 python -u <repo>/tests/e2e/ui_smoke.py <screenshot-dir>
Covers: lesson list, player seek, doubt chat (text + fake microphone), live class (start, interrupt), teacher dashboard (chapters, lecture view, selection).
Uses the cached Playwright Chromium; set CHROME to another binary if needed."""

import glob
import os
import sys
import time

from playwright.sync_api import sync_playwright

WEB = f"http://localhost:{os.environ.get('WEB_PORT', '5199')}"
CHROME = os.environ.get("CHROME") or sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
LESSON = os.environ.get("LESSON", "lesson-1-v2")
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, detail)


def wait_idle(page, scope, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if page.query_selector(f"{scope} .ask-status") is None and page.inner_text(f"{scope} .caption") and time.time() - t0 > 5:
            time.sleep(2)
            if page.query_selector(f"{scope} .ask-status") is None:
                return True
        time.sleep(1)
    return False


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--no-sandbox"])
    ctx = b.new_context(viewport={"width": 420, "height": 860}, permissions=["microphone"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(WEB + "/")
    page.wait_for_selector(".lesson-card")
    cards = page.query_selector_all(".lesson-card")
    check("home lists lessons with live-class links", len(cards) >= 5 and len(page.query_selector_all(".live-link")) == len(cards), f"{len(cards)} cards")

    page.goto(f"{WEB}/?lesson={LESSON}")
    page.wait_for_selector(".board")
    page.evaluate("""() => { const r = document.querySelector('input[type=range]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(r, '100'); r.dispatchEvent(new Event('input', {bubbles: true})); }""")
    time.sleep(1)
    check("player shows board items at 100 s", len(page.query_selector_all(".board .el")) >= 1)
    page.screenshot(path=f"{OUT}/ui-player.png")

    page.click(".ask-open")
    page.fill(".ask-text", "मैम, पदार्थ और वस्तु में क्या फ़र्क है?")
    page.click(".ask-btn.send")
    page.wait_for_selector(".bubble.teacher p", timeout=150000)
    check("chat answers with text bubble", len(page.query_selector_all(".bubble.child")) == 1 and len(page.inner_text(".bubble.teacher p")) > 30, page.inner_text(".bubble.teacher p")[:60])
    page.screenshot(path=f"{OUT}/ui-chat.png")
    page.click(".ask-bar .ask-btn:first-child"); time.sleep(3); page.click(".ask-btn.rec")
    page.wait_for_function("document.querySelectorAll('.bubble.teacher p').length >= 2 && !document.querySelector('.bubble .ask-status')", timeout=150000)
    check("microphone message is sent and answered (with voice)", "आवाज़" in page.inner_text(".chat-log") and page.query_selector(".chat-replay") is not None)

    page.goto(f"{WEB}/?lesson={LESSON}&live=1")
    page.wait_for_selector(".ask-start")
    page.click(".ask-start")
    t0 = time.time()
    while time.time() - t0 < 120 and not page.query_selector(".ask-plan li"):
        time.sleep(1)
    check("live class shows the plan", page.query_selector(".ask-plan li") is not None)
    if page.query_selector(".ask-btn.hand"):
        page.click(".ask-btn.hand")
        check("raise-hand stops the teacher", page.query_selector(".ask-btn.hand") is None)
    check("live class can continue", wait_idle(page, ".ask", 150) or page.query_selector(".ask-start") is not None)
    page.screenshot(path=f"{OUT}/ui-live.png")

    page.goto(WEB + "/?teacher=1")
    page.wait_for_selector(".t-lrow")
    check("dashboard lists chapter lessons", len(page.query_selector_all(".t-lrow")) >= 4)
    page.click(".t-lrow .t-btn.ok")
    page.wait_for_selector(".t-para")
    check("dashboard shows the lecture with pictures", len(page.query_selector_all(".t-pic")) >= 1)
    page.click(".t-pic")
    check("selecting a picture is shown", "picture:" in page.inner_text(".t-sel"))
    page.screenshot(path=f"{OUT}/ui-teacher.png")
    page.click("text=🎬 वीडियो")
    page.wait_for_selector(".t-para small")
    check("video tab lists the storyboard lines", len(page.query_selector_all(".t-para")) >= 10)
    page.click(".t-para")
    check("selecting a video line is shown", "line:" in page.inner_text(".t-sel"))
    page.screenshot(path=f"{OUT}/ui-video.png")
    check("no JavaScript errors", not errors, str(errors[:3]))
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; FAILED: {failed}" if failed else ""))
sys.exit(1 if failed else 0)
