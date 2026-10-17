"""Screenshots of every page at desktop and phone width + JS errors. Needs API + Vite. Run (outside services/api):
WEB_PORT=5198 uv run --offline --with playwright==1.63.0 python -u tests/e2e/ui_pages.py <screenshot-dir> [path ...]"""
import glob, os, sys
from playwright.sync_api import sync_playwright

WEB = f"http://localhost:{os.environ.get('WEB_PORT', '5198')}"
OUT = sys.argv[1]
PATHS = sys.argv[2:] or ["/", "/lessons", "/live", "/teacher", "/admin", "/?lesson=lesson-1-v2", "/teacher?chapter=ch6"]
CHROME = os.environ.get("CHROME") or sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
    for tag, w, h in [("d", 1360, 900), ("m", 400, 800)]:
        pg = b.new_page(viewport={"width": w, "height": h})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" and "favicon" not in m.text else None)
        for path in PATHS:
            pg.goto(WEB + path); pg.wait_for_timeout(1800)
            name = path.strip("/").replace("/", "_").replace("?", "_").replace("=", "-").replace("&", "_") or "home"
            pg.screenshot(path=f"{OUT}/{tag}-{name}.png", full_page=(tag == "m"))
    print("errors:", errors[:8])
