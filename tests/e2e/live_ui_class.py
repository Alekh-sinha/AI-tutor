"""Browser walk through a live class (topic class, one child = host): whenever the board changes, save a screenshot AND the sentence being spoken at that moment, so a human can check that what is on the screen matches what she says.
Needs API + vite (WEB_PORT). Run (outside services/api): WEB_PORT=5198 uv run --offline --with playwright==1.63.0 python -u tests/e2e/live_ui_class.py <dir> [topic] [seconds]"""
import glob, os, sys, time
from playwright.sync_api import sync_playwright
WEB = f"http://localhost:{os.environ.get('WEB_PORT', '5199')}"; OUT = sys.argv[1]; TOPIC = sys.argv[2] if len(sys.argv) > 2 else "घर्षण (friction)"; SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 240
os.makedirs(OUT, exist_ok=True)
CHROME = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"])
    pg = b.new_context(viewport={"width": 390, "height": 760}).new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{WEB}/?room=new"); pg.fill(".lr-input", "गुरुजी"); pg.click("text=नई कक्षा बनाएँ"); pg.wait_for_selector(".lr-code b")
    pg.fill("input[placeholder^='आज क्या']", TOPIC); pg.click("text=कक्षा शुरू करें")
    t0 = time.time(); last = None; n = 0; log = []; started = None
    while time.time() - t0 < SECONDS + 600:
        sig = pg.evaluate("() => [...document.querySelectorAll('.lr-board .el')].map(e => e.className.split(' ').pop() + ':' + (e.innerText || '').slice(0, 30)).join('|')")
        if started is None and sig: started = time.time()  # the class has started when the first screen appears (planning is over)
        if sig and sig != last:
            time.sleep(1.2)  # let the entrance animation finish
            n += 1; last = sig
            cap = pg.evaluate("() => (document.querySelector('.lr-caption')||{}).innerText || ''"); q = pg.evaluate("() => (document.querySelector('.lr-question')||{}).innerText || ''")
            pg.screenshot(path=f"{OUT}/screen-{n:02d}.png")
            clip = pg.evaluate("""() => { const b = document.querySelector('.lr-board .board'); if (!b) return null; const r = b.getBoundingClientRect(); return {boardH: Math.round(r.height), clipped: [...b.children].some(c => { const q = c.getBoundingClientRect(); return q.top < r.top - 2 || q.bottom > r.bottom + 2; })}; }""")
            log.append((n, round(time.time() - t0), sig, cap, q, clip)); print(f"[{n:02d}] t={round(time.time()-(started or t0))}s board={sig!r} clip={clip}\n     speaking: {cap!r} question: {q!r}", flush=True)
        if pg.query_selector(".lr-done") and started and time.time() - started > 30: break
        if started and time.time() - started > SECONDS: break
        time.sleep(0.7)
    print("JS errors:", errs, "| screens:", n)
    b.close()
