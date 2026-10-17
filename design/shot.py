import glob,os,sys
from playwright.sync_api import sync_playwright
C=sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))[-1]
out=sys.argv[1]; errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=C,headless=True,args=["--no-sandbox"])
    for name,w,h in [("d",1400,900),("m",400,820)]:
        pg=b.new_page(viewport={"width":w,"height":h}); pg.on("pageerror",lambda e:errs.append(str(e)))
        for r in ["home","lessons","player","live","room","teacher"]:
            pg.goto(f"file:///home/alekh/Projects/ai-teacher/design/mockup/index.html#/{r}"); pg.wait_for_timeout(500)
            pg.screenshot(path=f"{out}/{name}-{r}.png",full_page=(name=="m"))
        for r in ["teacher/chapter","teacher/lesson/1/lecture","teacher/lesson/3/video","teacher/lesson/1/publish","teacher/lesson/3/publish","teacher/published"]:
            pg.goto("file:///home/alekh/Projects/ai-teacher/design/mockup/index.html#/"+r); pg.wait_for_timeout(400)
            pg.screenshot(path=f"{out}/{name}-"+r.replace("/","-")+".png")
    print("errors",errs)
