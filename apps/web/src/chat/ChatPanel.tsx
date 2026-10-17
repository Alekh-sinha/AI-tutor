import { useEffect, useRef, useState } from "react";
import { photoToBase64, startRecording, type Recorder } from "./media";
import { useSimpleChat } from "./useSimpleChat";

/** Bold marks (**word**) the model may still write, shown as bold instead of raw asterisks. */
const Rich = ({ text }: { text: string }) => <>{text.split(/\*\*/).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))}</>;

/** ChatGPT-style chat with the teacher: type, speak or send a photo; read the answer, hear it too when you spoke (or turned the speaker on). */
export function ChatPanel({ lessonId = "", getTime = () => 0, onClose }: { lessonId?: string; getTime?: () => number; onClose: () => void }) {
  const { msgs, busy, status, thoughts, send, play, stop } = useSimpleChat(lessonId, getTime);
  const [text, setText] = useState("");
  const [rec, setRec] = useState<Recorder | null>(null);
  const [speaker, setSpeaker] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const debug = new URLSearchParams(location.search).has("debug");
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const submit = () => { if (text.trim()) { void send({ text: text.trim() }, speaker); setText(""); } };
  const toggleMic = async () => {
    if (rec) { const b64 = await rec.stop(); setRec(null); void send({ audioB64: b64 }, true); return; }
    try { setRec(await startRecording()); } catch { alert("माइक की अनुमति नहीं मिली।"); }
  };
  const pickPhoto = async (f?: File) => { if (f) void send({ imageB64: await photoToBase64(f), text: text.trim() || undefined }, speaker); setText(""); };

  return (
    <div className="ask">
      <div className="ask-head">
        <b>💬 टीचर से बात करें</b>
        <button className={`ask-btn ${speaker ? "on" : ""}`} onClick={() => { setSpeaker(!speaker); stop(); }} aria-label="आवाज़ में जवाब" title="आवाज़ में जवाब">{speaker ? "🔊" : "🔇"}</button>
        <button className="ask-close" onClick={() => { stop(); onClose(); }} aria-label="बंद करें">✕</button>
      </div>
      <div className="chat-log">
        {msgs.length === 0 && (
          <div className="chat-hint">
            <p>कोई भी सवाल पूछिए — लिखकर, बोलकर या फोटो भेजकर।</p>
            <div className="chat-suggest">
              {["पानी में नमक क्यों घुल जाता है?", "बादल कैसे बनते हैं?", "लोहा चमकता क्यों है?"].map((q) => <button key={q} onClick={() => void send({ text: q }, speaker)}>{q}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={`bubble ${m.who}`}>
            {m.image && <figure><img src={m.image.src} alt={m.image.caption} />{m.image.caption && <figcaption>{m.image.caption}</figcaption>}</figure>}
            {m.kind === "voice" && !m.text && <span>🎤 (आवाज़)</span>}
            {m.text && <p><Rich text={m.text} /></p>}
            {m.audio && <button className="chat-replay" onClick={() => play(m.audio!)}>🔊 फिर सुनें</button>}
          </div>
        ))}
        {busy && <div className="bubble teacher"><span className="ask-status">⏳ {status}</span></div>}
        {debug && thoughts.length > 0 && <pre className="ask-thoughts">{thoughts.join("\n\n")}</pre>}
        <div ref={end} />
      </div>
      <div className="ask-bar">
        <button className={`ask-btn ${rec ? "rec" : ""}`} onClick={toggleMic} disabled={busy} aria-label="बोलकर पूछें">{rec ? "⏹" : "🎤"}</button>
        <button className="ask-btn" onClick={() => file.current?.click()} disabled={busy} aria-label="फोटो भेजें">📷</button>
        <input ref={file} type="file" accept="image/*" capture="environment" hidden onChange={(e) => void pickPhoto(e.target.files?.[0])} />
        <input className="ask-text" value={text} placeholder="सवाल लिखिए…" maxLength={600} disabled={busy} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
        <button className="ask-btn send" onClick={submit} disabled={busy || !text.trim()} aria-label="भेजें">➤</button>
      </div>
    </div>
  );
}
