import { useCallback, useEffect, useRef, useState } from "react";
import { PcmPlayer, startMicStream, type Mic } from "./audio";

export interface Person { id: string; name: string; host: boolean }
export interface BoardEl { type: "note" | "image" | "figure"; id: string; text?: string; style?: string; src?: string; caption?: string; html?: string; name?: string }
export interface RoomState {
  code: string; started: boolean; finished?: boolean; members: Person[]; queue: { id: string; name: string }[]; floor: string | null; floor_name: string; teacher_busy: boolean; plan: string[];
}
/** Where in the teacher's speech a board change belongs: the turn number and the character offset in that turn's caption text. */
interface Pos { turn?: number; at_char?: number; late?: boolean }
type Msg =
  | ({ type: "state" } & RoomState)
  | ({ type: "snapshot"; board: BoardEl[] } & RoomState)
  | { type: "hello"; id: string; host: boolean; lesson_id: string }
  | { type: "caption"; delta: string; turn?: number }
  | { type: "caption_end"; turn?: number }
  | { type: "heard"; name: string; delta: string }
  | { type: "interrupted" }
  | { type: "plan"; steps: string[] }
  | ({ type: "board"; op: "add"; el: BoardEl } & Pos)
  | ({ type: "board"; op: "hide"; id: string } & Pos)
  | ({ type: "board"; op: "clear" } & Pos)
  | ({ type: "board"; op: "set"; els: BoardEl[] } & Pos)
  | { type: "question"; text: string }
  | { type: "thinking"; text: string }
  | { type: "ended"; reason: string };

const EMPTY: RoomState = { code: "", started: false, finished: false, members: [], queue: [], floor: null, floor_name: "", teacher_busy: false, plan: [] };

/** One child's connection to a live class room: the teacher's voice + captions + board come in, this child's microphone/text/hand go out (only while they hold the floor). */
export function useLiveRoom(code: string, name: string, hostKey: string) {
  const [state, setState] = useState<RoomState>(EMPTY);
  const [me, setMe] = useState({ id: "", host: false });
  const [board, setBoard] = useState<BoardEl[]>([]);
  const [caption, setCaption] = useState("");
  const [heard, setHeard] = useState<{ name: string; text: string }[]>([]);
  const [status, setStatus] = useState("");
  const [question, setQuestion] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [ended, setEnded] = useState("");
  const [connected, setConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);
  const player = useRef(new PcmPlayer());
  const mic = useRef<Mic | null>(null);
  const micOn = useRef(false);
  const captionDone = useRef(false);
  const talkRef = useRef(false);
  const [talking, setTalking] = useState(false);
  /** Captions arrive long before their audio has played (the model talks faster than real time). Each piece waits here until the audio clock reaches it, so the words on screen match the words heard,
   *  and an interruption throws away the words that were never spoken. */
  const capQ = useRef<{ at: number; m: Msg }[]>([]);
  /** Index in `board` where the current scene starts: a new scene begins with the first board item after a teacher turn has been fully spoken. */
  const [sceneStart, setSceneStart] = useState(0);
  const turnOver = useRef(false);
  const meRef = useRef("");
  const boardLen = useRef(0);
  /** Apply one timeline message (caption text, end of a turn, board change, plan) when the audio it belongs to is being played. */
  const apply = (m: Msg) => {
    switch (m.type) {
      case "caption": setCaption((cur) => (captionDone.current ? m.delta : cur + m.delta)); captionDone.current = false; break;
      case "caption_end": captionDone.current = true; turnOver.current = true; break;
      case "plan": setState((s) => ({ ...s, plan: m.steps })); break;
      case "board":
        if (m.op === "add" && turnOver.current) { turnOver.current = false; setSceneStart(boardLen.current); }
        if (m.op === "clear") { turnOver.current = false; setSceneStart(0); }
        setBoard((b) => { const n = m.op === "set" ? m.els : m.op === "add" ? [...b, m.el] : m.op === "hide" ? b.filter((x) => x.id !== m.id) : []; boardLen.current = n.length; return n; });
        break;
    }
  };
  const enqueue = (m: Msg) => {
    const t = player.current.playedAt();
    if (!t || (m.type === "board" && m.late)) { apply(m); return; }  // a picture that finished drawing is shown at once; everything else when the voice reaches this point of the stream
    const q = capQ.current;
    q.push({ at: t.end, m });
  };

  useEffect(() => {
    const p = player.current;
    const tick = setInterval(() => {
      const t = p.playedAt();
      while (capQ.current.length && (!t || capQ.current[0].at <= t.now + 0.15)) apply(capQ.current.shift()!.m);
    }, 80);
    p.onSpeaking = setSpeaking;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${location.host}/api/live/ws/${code}?name=${encodeURIComponent(name)}&key=${encodeURIComponent(hostKey)}`);
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    sock.onopen = () => setConnected(true);
    sock.onclose = () => { if (ws.current !== sock) return; setConnected(false); setEnded((e) => e || "कनेक्शन टूट गया।"); };  // a socket replaced by React StrictMode's remount is not a lost connection
    sock.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) { p.push(ev.data); setStatus(""); return; }
      const m = JSON.parse(ev.data) as Msg;
      switch (m.type) {
        case "hello": meRef.current = m.id; setMe({ id: m.id, host: m.host }); break;
        case "snapshot": setState(m); setBoard(m.board); boardLen.current = m.board.length; setSceneStart(Math.max(0, m.board.length - 4)); break;
        case "state": setState(m); break;
        case "caption": case "caption_end": case "plan": case "board": enqueue(m); break;
        case "heard": setHeard((h) => (h.length && h[h.length - 1].name === m.name ? [...h.slice(0, -1), { name: m.name, text: h[h.length - 1].text + m.delta }] : [...h.slice(-4), { name: m.name, text: m.delta }])); break;
        case "interrupted": {
          p.flush();
          const keep = capQ.current.filter((q) => q.m.type !== "caption" && q.m.type !== "caption_end");  // unspoken words are dropped, board changes still happen
          capQ.current = [];
          keep.forEach((q) => apply(q.m));
          break;
        }
        case "thinking": setStatus(m.text); break;
        case "question": setQuestion(m.text); break;
        case "ended": setEnded(m.reason); break;
      }
    };
    return () => { clearInterval(tick); if (ws.current === sock) ws.current = null; sock.close(); mic.current?.stop(); p.close(); };
  }, [code, name, hostKey]);

  const send = useCallback((ev: object) => { if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(ev)); }, []);

  const iHaveFloor = state.floor === me.id && !!me.id;
  const solo = state.members.length === 1;

  /** Push-to-talk: the microphone is opened ONLY when the child presses "speak" and closed on "done", so the room, the loudspeaker and people nearby never reach the teacher. */
  const stopMic = useCallback(() => { talkRef.current = false; setTalking(false); micOn.current = false; mic.current?.stop(); mic.current = null; }, []);
  const talk = useCallback(() => {
    if (talkRef.current) return;
    if (!iHaveFloor && !solo) { send({ type: "talk", on: true }); return; }  // the server turns this into a raised hand
    talkRef.current = true;
    setTalking(true);
    player.current.flush();  // her voice stops at once
    capQ.current.filter((q) => q.m.type === "board" || q.m.type === "plan").forEach((q) => apply(q.m));
    capQ.current = [];
    send({ type: "talk", on: true });
    micOn.current = true;
    startMicStream((pcm) => { if (talkRef.current && ws.current?.readyState === WebSocket.OPEN) ws.current.send(pcm); })
      .then((m) => { if (micOn.current) mic.current = m; else m.stop(); })
      .catch(() => { stopMic(); setStatus("माइक की अनुमति नहीं मिली — लिखकर जवाब दीजिए।"); });
  }, [iHaveFloor, solo, send, stopMic]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!iHaveFloor && !solo && talkRef.current) stopMic(); }, [iHaveFloor, solo, stopMic]);

  return {
    state, me, board, sceneStart, caption, heard, status, question, speaking, ended, connected, iHaveFloor,
    unlock: () => player.current.unlock(),
    start: (topic: string) => send({ type: "start", topic }),
    next: () => send({ type: "continue" }),
    hand: () => send({ type: "hand" }),
    lower: () => send({ type: "lower" }),
    done: () => { stopMic(); send({ type: "done" }); },
    grant: () => send({ type: "grant" }),
    talk, talking, solo,
    say: (text: string) => send({ type: "text", text }),
  };
}
