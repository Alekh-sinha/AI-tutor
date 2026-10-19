import { useCallback, useEffect, useRef, useState } from "react";
import { playAnswer, stopAnswer } from "./audio";
import { newSessionId, streamChat } from "./sse";

export interface Msg { id: number; who: "child" | "teacher"; text?: string; image?: { src: string; caption: string }; audio?: string | null; kind?: "text" | "voice" | "photo" }
type ServerEvent =
  | { type: "thinking"; text: string }
  | { type: "thought"; text: string }
  | { type: "board"; op: "add"; el: { type: "image"; src: string; caption?: string } }
  | { type: "board"; op: string }
  | { type: "text"; text: string; audio: string | null }
  | { type: "error"; text: string }
  | { type: "done" };

export interface Send { text?: string; imageB64?: string; audioB64?: string }

const SLOW_HINT_MS = 45_000;  // still waiting: say so
const GIVE_UP_MS = 120_000;   // an answer normally takes 10-20 s (a new picture adds up to 45 s): stop waiting and let the child ask again

/** Plain chat with the teacher (POST /api/chat, mode "chat"): messages in, a text answer (plus voice when the child spoke or asked for it, plus a picture now and then) out. */
export function useSimpleChat(lessonId: string, getTime: () => number) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [thoughts, setThoughts] = useState<string[]>([]);
  const session = useRef(newSessionId());
  const next = useRef(1);
  const ctrl = useRef<AbortController | null>(null);
  const turn = useRef(0);  // number of the latest question: events of an older question (or of a closed panel) are ignored

  // closing the panel cancels the request (the server stops its work when the connection closes), drops what still arrives, and stops the voice
  useEffect(() => () => { turn.current = -1; ctrl.current?.abort(); stopAnswer(); }, []);

  const send = useCallback(async (m: Send, voiceReply: boolean) => {
    if (busy) return;
    const mine = ++turn.current;
    const live = () => turn.current === mine;
    ctrl.current = new AbortController();
    const mine_ctrl = ctrl.current;
    let gaveUp = false;
    const hint = setTimeout(() => { if (live()) setStatus("आज जवाब आने में थोड़ा ज़्यादा समय लग रहा है…"); }, SLOW_HINT_MS);
    const giveUp = setTimeout(() => { gaveUp = true; mine_ctrl.abort(); }, GIVE_UP_MS);
    stopAnswer();
    setBusy(true); setStatus("सोच रहा हूँ…"); setThoughts([]);
    const kind = m.audioB64 ? "voice" : m.imageB64 && !m.text ? "photo" : "text";
    setMsgs((x) => [...x, { id: next.current++, who: "child", text: m.text, kind, ...(m.imageB64 ? { image: { src: `data:image/jpeg;base64,${m.imageB64}`, caption: "" } } : {}) }]);
    try {
      await streamChat<ServerEvent>(
        { session_id: session.current, lesson_id: lessonId, mode: "chat", t: getTime(), text: m.text ?? "", image_b64: m.imageB64, audio_b64: m.audioB64, voice_reply: voiceReply },
        mine_ctrl.signal,
        (e) => {
          if (!live()) return;
          if (e.type === "thinking") setStatus(e.text);
          else if (e.type === "thought") setThoughts((t) => [...t, e.text]);
          else if (e.type === "board" && e.op === "add" && "el" in e) {
            const el = e.el;
            setMsgs((x) => [...x, { id: next.current++, who: "teacher", image: { src: el.src, caption: el.caption ?? "" } }]);
          } else if (e.type === "text") {
            setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: e.text, audio: e.audio }]);
            if (e.audio) playAnswer(e.audio);
          } else if (e.type === "error") setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: e.text }]);
        });
    } catch (err) {
      if (live()) setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: gaveUp ? "जवाब नहीं आ पाया। कृपया फिर से पूछिए।" : err instanceof Error ? err.message : "कुछ गड़बड़ हो गई।" }]);
    } finally {
      clearTimeout(hint); clearTimeout(giveUp);
      if (live()) { setBusy(false); setStatus(""); }
    }
  }, [busy, lessonId, getTime]);

  return { msgs, busy, status, thoughts, send, play: playAnswer, stop: stopAnswer };
}
