import { useRef, useState } from "react";
import { Board } from "../player/Board";
import type { BoardElement } from "../player/board";
import { photoToBase64, startRecording, type Recorder } from "./media";
import { useChat } from "./useChat";

/** Full-screen live class: the teacher teaches step by step with voice + a live whiteboard; the child answers by text, voice or photo, presses continue, or raises a hand.
 * With a lesson id the class is on that lesson; with none, the child's first message says what they want to learn and the teacher prepares for it first. */
export function LiveClass({ lessonId, getTime, onClose }: { lessonId: string; getTime: () => number; onClose: () => void }) {
  const { elements, caption, status, plan, thoughts, busy, question, ask, stopSpeaking, interrupt } = useChat(lessonId, getTime);
  const [started, setStarted] = useState(false);
  const needStart = !!lessonId && !started;  // a class on the child's own topic starts with their first message instead
  const [text, setText] = useState("");
  const [rec, setRec] = useState<Recorder | null>(null);
  const [showThoughts, setShowThoughts] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const debug = new URLSearchParams(location.search).has("debug");

  const send = () => { if (text.trim()) { void ask({ text: text.trim() }); setText(""); } };
  const toggleMic = async () => {
    if (rec) { const b64 = await rec.stop(); setRec(null); void ask({ audioB64: b64 }); return; }
    try { setRec(await startRecording()); } catch { alert("माइक की अनुमति नहीं मिली।"); }
  };
  const pickPhoto = async (f?: File) => { if (f) void ask({ imageB64: await photoToBase64(f), text: text.trim() || undefined }); setText(""); };

  return (
    <div className="ask">
      <div className="ask-head">
        <b>🎓 लाइव क्लास</b>
        <button className="ask-close" onClick={() => { stopSpeaking(); onClose(); }} aria-label="बंद करें">✕</button>
      </div>
      {question && <p className="ask-q">🧒 {question}</p>}
      <Board state={{ elements: elements.map((e) => e as unknown as BoardElement), highlighted: null, anims: {} }} time={0} />
      {plan.length > 0 && (
        <ol className="ask-plan">{plan.map((s, i) => <li key={i}>{s}</li>)}</ol>
      )}
      <p className="caption">{caption || (busy ? "" : lessonId ? "" : "आप क्या सीखना चाहते हैं? लिखिए, बोलिए या किताब के पन्ने की फोटो भेजिए।")}</p>
      {busy && status && <p className="ask-status">⏳ {status}</p>}
      {debug && thoughts.length > 0 && (
        <button className="ask-debug" onClick={() => setShowThoughts(!showThoughts)}>{showThoughts ? "▾" : "▸"} सोच ({thoughts.length})</button>
      )}
      {debug && showThoughts && <pre className="ask-thoughts">{thoughts.join("\n\n")}</pre>}
      {needStart && (
        <button className="ask-start" onClick={() => { setStarted(true); void ask({ text: "कक्षा शुरू कीजिए" }); }}>▶ कक्षा शुरू करें</button>
      )}
      {!needStart && !!question && (
        <div className="ask-live">
          {busy ? <button className="ask-btn hand" onClick={interrupt}>✋ रुकिए</button> : <button className="ask-start" onClick={() => void ask({ text: "आगे बढ़िए" })}>▶ आगे बढ़िए</button>}
        </div>
      )}
      <div className="ask-bar">
        <button className={`ask-btn ${rec ? "rec" : ""}`} onClick={toggleMic} disabled={busy || needStart} aria-label="बोलकर पूछें">{rec ? "⏹" : "🎤"}</button>
        <button className="ask-btn" onClick={() => file.current?.click()} disabled={busy || needStart} aria-label="फोटो भेजें">📷</button>
        <input ref={file} type="file" accept="image/*" capture="environment" hidden onChange={(e) => void pickPhoto(e.target.files?.[0])} />
        <input className="ask-text" value={text} placeholder={lessonId ? "जवाब लिखिए…" : "मैं ... सीखना चाहता हूँ"} maxLength={600} disabled={busy || needStart}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="ask-btn send" onClick={send} disabled={busy || !text.trim()} aria-label="भेजें">➤</button>
      </div>
    </div>
  );
}
