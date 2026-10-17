"""Render the spike fragments at phone width with headless chromium."""
import sys, pathlib
from playwright.sync_api import sync_playwright
src = pathlib.Path(sys.argv[1]); font = pathlib.Path(sys.argv[2]).resolve()
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 360, "height": 320}, device_scale_factor=2)
    for f in sorted(src.glob("*.html")):
        page = f"""<!doctype html><meta charset=utf-8><style>@font-face{{font-family:D;src:url(file://{font})}}body{{margin:0;background:#fff;font-family:D,sans-serif;color:#1f2937}}#b{{width:340px;margin:10px;max-height:280px;overflow:hidden;outline:1px dashed #ccc}}</style><div id=b>{f.read_text()}</div>"""
        pg.set_content(page); pg.wait_for_timeout(600)
        over = pg.evaluate("(()=>{const e=document.querySelector('#b');return [e.scrollWidth>e.clientWidth, e.scrollHeight>e.clientHeight, e.scrollHeight]})()")
        pg.screenshot(path=str(src / f"{f.stem}.png"))
        print(f.stem, "overflowX/Y/height:", over)
    b.close()
