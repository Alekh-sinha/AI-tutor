"""Browser test of the streaming live class with TWO browsers (host + child), fake microphone. Needs API :8000 and vite :5199.
Run (outside services/api): uv run --offline --with playwright==1.63.0 python -u tests/e2e/live_ui_smoke.py <screenshot-dir>"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

WEB = f"http://localhost:{os.environ.get('WEB_PORT', '5199')}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
LESSON = os.environ.get("LESSON", "lesson-1-v2")
import glob

CHROME = os.environ.get("CHROME") or sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, detail, flush=True)


def wait(pred, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(1)
    return False


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--no-sandbox"])
    errors = []

    def new_page():
        ctx = b.new_context(viewport={"width": 420, "height": 860}, permissions=["microphone"])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        return pg

    host, kid = new_page(), new_page()
    host.goto(f"{WEB}/?room=new&lesson={LESSON}")
    host.fill(".lr-input", "गुरुजी")
    host.click("text=लाइव क्लास शुरू करें")
    host.wait_for_selector(".lr-code b")
    code = host.inner_text(".lr-code b")
    check("host created a class with a 5-digit code", len(code) == 5 and code.isdigit(), code)

    kid.goto(f"{WEB}/?join=1")
    kid.fill("input[placeholder='आपका नाम']", "रानी")
    kid.fill("input[inputmode=numeric]", code)
    kid.click("text=कक्षा में जुड़ें")
    kid.wait_for_selector(".lr-code b")
    check("child joined, host sees 2 people", wait(lambda: "2" in host.inner_text(".lr-people"), 10))

    host.click("text=कक्षा शुरू करें")
    kid.wait_for_selector(".lr-unlock")
    kid.click(".lr-unlock")
    check("teacher caption appears for the child", wait(lambda: len(kid.inner_text(".lr-caption")) > 15, 90), kid.inner_text(".lr-caption")[:60])
    check("teacher avatar animates while the voice plays", wait(lambda: kid.query_selector(".lr-teacher.talking") is not None, 30))
    check("board gets an item for the child", wait(lambda: len(kid.query_selector_all(".lr-board .el")) >= 1, 90))
    kid.screenshot(path=f"{OUT}/live-child.png")
    board_h = kid.evaluate("document.querySelector('.lr-board').getBoundingClientRect().height")
    cap_px = kid.evaluate("parseFloat(getComputedStyle(document.querySelector('.lr-caption')).fontSize)")
    check("whiteboard is big (>= 35% of the screen) and the subtitle is small", board_h >= 0.35 * 860 and cap_px <= 17, f"board {board_h:.0f}px of 860, subtitle {cap_px}px")
    host.screenshot(path=f"{OUT}/live-host.png")

    kid.click("text=हाथ उठाइए")
    check("child gets the floor after the teacher's turn", wait(lambda: kid.query_selector(".lr-mine") is not None, 150))
    kid.screenshot(path=f"{OUT}/live-floor.png")
    if kid.query_selector(".lr-mine"):
        check("microphone is NOT open until the child presses speak", kid.query_selector("text=सुन रही हूँ") is None)
        kid.click(".lr-talk")
        check("pressing speak opens the microphone", wait(lambda: kid.query_selector("text=सुन रही हूँ") is not None, 10))
        time.sleep(4)  # fake microphone streams a beep tone
        kid.click("text=बोल दिया")
        check("floor is released after 'done'", wait(lambda: kid.query_selector(".lr-mine") is None, 10))
    check("host can press continue", host.query_selector("text=आगे बढ़िए") is not None)
    check("no JavaScript errors", not errors, str(errors[:3]))
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; FAILED: {failed}" if failed else ""))
sys.exit(1 if failed else 0)
