import DOMPurify from "dompurify";
import { useEffect, useRef } from "react";

/** A figure written by the planner (HTML + CSS, no script). Second safety layer after the server's check (live/figures.py): DOMPurify strips scripts, handlers and external references, and the markup lives in a Shadow DOM so its <style> cannot touch the rest of the page. */
export function Figure({ html }: { html: string }) {
  const box = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const root = el.shadowRoot ?? el.attachShadow({ mode: "open" });
    const clean = DOMPurify.sanitize(html, { ADD_TAGS: ["style"], FORBID_TAGS: ["script", "iframe", "img", "a", "form", "input", "link", "object", "embed"], FORBID_ATTR: ["href", "src", "srcset", "xlink:href"], WHOLE_DOCUMENT: false });
    root.innerHTML = `<style>:host{display:block;contain:layout paint;font-family:inherit;color:#1f2937}*{box-sizing:border-box}</style>${clean}`;
  }, [html]);
  /** Shrink the figure to the room the board has left (never scroll, never cut): scale = available height / natural height. */
  useEffect(() => {
    const b = box.current, h = host.current;
    if (!b || !h) return;
    const fit = () => {
      h.style.transform = "none";
      const avail = b.clientHeight, natural = h.scrollHeight;
      const s = avail > 0 ? Math.min(1, avail / Math.max(natural, 1)) : 1;
      h.style.transform = `scale(${s})`;
      h.style.transformOrigin = "top center";
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(b);
    return () => ro.disconnect();
  }, [html]);
  return <div ref={box} className="figure-box"><div ref={host} className="figure-host" /></div>;
}
