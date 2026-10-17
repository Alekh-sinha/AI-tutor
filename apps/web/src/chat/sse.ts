import { readError } from "../ss/api";

/** POST to /api/chat and call `onEvent` for every server-sent event (the stream ends with {type:"done"}). Throws on HTTP errors. */
export async function streamChat<E>(body: unknown, signal: AbortSignal, onEvent: (e: E) => void): Promise<void> {
  const r = await fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json" }, signal, body: JSON.stringify(body) });
  if (!r.ok || !r.body) {
    const e = await readError(r);
    throw new Error(e.code !== "error" ? e.message : r.status === 429 ? "आज के लिए इतने सवाल काफ़ी हैं।" : "सर्वर से जवाब नहीं मिला।");
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as E);
    }
  }
}

export const newSessionId = () => (crypto.randomUUID?.() ?? String(Math.random()).slice(2) + Date.now()).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40).padEnd(8, "x");
