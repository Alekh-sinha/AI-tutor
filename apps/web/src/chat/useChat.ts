import { useCallback, useRef, useState } from "react";
import { newSessionId, streamChat } from "./sse";

export interface ChatElement { type: "note" | "image"; id: string; t: number; text?: string; style?: string; src?: string; caption?: string }
type ServerEvent =
  | { type: "thinking"; text: string }
  | { type: "thought"; text: string }
  | { type: "plan"; steps: string[] }
  | { type: "board"; op: "add"; el: ChatElement }
  | { type: "board"; op: "hide"; id: string }
  | { type: "board"; op: "clear" }
  | { type: "say"; text: string; audio: string | null }
  | { type: "error"; text: string; detail?: string }
  | { type: "done" };

export interface Ask { text?: string; imageB64?: string; audioB64?: string }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Live class: talks to POST /api/chat (mode "teach") and replays what the teacher agent did, IN ORDER: board changes appear when the teacher gets to them,
 * and each spoken sentence is played to its end before the next step, so voice and board stay together like a teacher writing while talking.
 */
export function useChat(lessonId: string, getTime: () => number) {
  const [elements, setElements] = useState<ChatElement[]>([]);
  const [caption, setCaption] = useState("");
  const [status, setStatus] = useState("");
  const [plan, setPlan] = useState<string[]>([]);
  const [thoughts, setThoughts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const session = useRef(newSessionId());
  const queue = useRef<ServerEvent[]>([]);
  const pumping = useRef(false);
  const streamDone = useRef(true);
  const audio = useRef<HTMLAudioElement | null>(null);
  const abort = useRef<AbortController | null>(null);
  const captionRef = useRef("");
  const interrupted = useRef("");

  const finishIfIdle = useCallback(() => {
    if (streamDone.current && queue.current.length === 0 && !pumping.current) { setBusy(false); setStatus(""); }
  }, []);

  const speak = (b64: string) =>
    new Promise<void>((resolve) => {
      const a = new Audio(`data:audio/mpeg;base64,${b64}`);
      audio.current = a;
      a.onended = () => resolve();
      a.onerror = () => resolve();
      a.play().catch(() => resolve());
    });

  const pump = useCallback(async () => {
    if (pumping.current) return;
    pumping.current = true;
    while (queue.current.length) {
      const e = queue.current.shift()!;
      if (e.type === "thinking") setStatus(e.text);
      else if (e.type === "thought") setThoughts((t) => [...t, e.text]);
      else if (e.type === "plan") setPlan(e.steps);
      else if (e.type === "board") {
        if (e.op === "add") setElements((els) => [...els, e.el]);
        else if (e.op === "hide") setElements((els) => els.filter((x) => x.id !== e.id));
        else setElements([]);
        await sleep(450);
      } else if (e.type === "say") {
        setStatus("");
        setCaption(e.text);
        captionRef.current = e.text;
        if (e.audio) await speak(e.audio);
        else await sleep(Math.min(6000, 60 * e.text.length));
      } else if (e.type === "error") { setCaption(e.text); }
    }
    pumping.current = false;
    finishIfIdle();
  }, [finishIfIdle]);

  const ask = useCallback(async (a: Ask) => {
    if (busy) return;
    setBusy(true); setPlan([]); setThoughts([]); setCaption(""); setStatus("सोच रहा हूँ…");
    setQuestion(a.text || (a.audioB64 ? "🎤 (आवाज़)" : "📷 (फोटो)"));
    streamDone.current = false;
    const ctl = new AbortController();
    abort.current = ctl;
    const interruptedAfter = interrupted.current;
    interrupted.current = "";
    try {
      await streamChat<ServerEvent>(
        { session_id: session.current, lesson_id: lessonId, mode: "teach", t: getTime(), text: a.text ?? "", image_b64: a.imageB64, audio_b64: a.audioB64, interrupted_after: interruptedAfter },
        ctl.signal, (e) => { queue.current.push(e); void pump(); });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;  // the child interrupted: nothing to report
      queue.current.push({ type: "error", text: err instanceof Error ? err.message : "कुछ गड़बड़ हो गई।" });
      void pump();
    } finally {
      streamDone.current = true;
      finishIfIdle();
    }
  }, [busy, lessonId, getTime, pump, finishIfIdle]);

  const stopSpeaking = useCallback(() => { audio.current?.pause(); }, []);
  /** The child raises a hand: stop the voice, drop what the teacher had still to do, remember where she was. */
  const interrupt = useCallback(() => {
    interrupted.current = captionRef.current;
    abort.current?.abort();
    queue.current = [];
    audio.current?.pause();
    streamDone.current = true;
    pumping.current = false;
    setBusy(false); setStatus("");
  }, []);
  return { elements, caption, status, plan, thoughts, busy, question, ask, stopSpeaking, interrupt };
}
