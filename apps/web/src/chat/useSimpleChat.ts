import { useCallback, useRef, useState } from "react";
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

/** Plain chat with the teacher (POST /api/chat, mode "chat"): messages in, a text answer (plus voice when the child spoke or asked for it, plus a picture now and then) out. */
export function useSimpleChat(lessonId: string, getTime: () => number) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [thoughts, setThoughts] = useState<string[]>([]);
  const session = useRef(newSessionId());
  const next = useRef(1);
  const player = useRef<HTMLAudioElement | null>(null);

  const play = useCallback((b64: string) => {
    player.current?.pause();
    const a = new Audio(`data:audio/mpeg;base64,${b64}`);
    player.current = a;
    void a.play().catch(() => undefined);
  }, []);

  const send = useCallback(async (m: Send, voiceReply: boolean) => {
    if (busy) return;
    setBusy(true); setStatus("सोच रहा हूँ…"); setThoughts([]);
    const kind = m.audioB64 ? "voice" : m.imageB64 && !m.text ? "photo" : "text";
    setMsgs((x) => [...x, { id: next.current++, who: "child", text: m.text, kind, ...(m.imageB64 ? { image: { src: `data:image/jpeg;base64,${m.imageB64}`, caption: "" } } : {}) }]);
    try {
      await streamChat<ServerEvent>(
        { session_id: session.current, lesson_id: lessonId, mode: "chat", t: getTime(), text: m.text ?? "", image_b64: m.imageB64, audio_b64: m.audioB64, voice_reply: voiceReply },
        new AbortController().signal,
        (e) => {
          if (e.type === "thinking") setStatus(e.text);
          else if (e.type === "thought") setThoughts((t) => [...t, e.text]);
          else if (e.type === "board" && e.op === "add" && "el" in e) {
            const el = e.el;
            setMsgs((x) => [...x, { id: next.current++, who: "teacher", image: { src: el.src, caption: el.caption ?? "" } }]);
          } else if (e.type === "text") {
            setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: e.text, audio: e.audio }]);
            if (e.audio) play(e.audio);
          } else if (e.type === "error") setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: e.text }]);
        });
    } catch (err) {
      setMsgs((x) => [...x, { id: next.current++, who: "teacher", text: err instanceof Error ? err.message : "कुछ गड़बड़ हो गई।" }]);
    } finally { setBusy(false); setStatus(""); }
  }, [busy, lessonId, getTime, play]);

  return { msgs, busy, status, thoughts, send, play, stop: () => player.current?.pause() };
}
