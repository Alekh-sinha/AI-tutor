import "./live/live.css";
import { useEffect, useRef, useState } from "react";
import type { Lesson } from "../../../packages/lesson-schema/lesson";
import { Board } from "./player/Board";
import { boardAt, captionAt, thinkingAt } from "./player/board";
import { ChatPanel } from "./chat/ChatPanel";
import { LiveClass } from "./chat/LiveClass";
import { LiveEntry } from "./live/LiveEntry";
import { Teacher } from "./teacher/Teacher";
import { Ended } from "./player/Ended";
import { ThinkClock } from "./player/ThinkClock";
import { usePlayer } from "./player/usePlayer";
import "./App.css";

function Player({ lesson }: { lesson: Lesson }) {
  const { time, playing, toggle, seek } = usePlayer(lesson);
  const think = thinkingAt(lesson, time);
  const ended = time >= lesson.duration && !playing && !!lesson.activity;
  const [asking, setAsking] = useState(false);
  const live = new URLSearchParams(location.search).has("live");
  const timeRef = useRef(time);
  timeRef.current = time;
  return (
    <div className="player">
      <div className="topbar">
        <a className="back" href="/" aria-label="सभी पाठ">←</a>
        <h1 className="lesson-title">{lesson.title}</h1>
      </div>
      {ended ? (
        <div className="board"><Ended activity={lesson.activity} onReplay={() => { seek(0); toggle(); }} /></div>
      ) : (
        <Board state={boardAt(lesson, time)} time={time} />
      )}
      {think ? <ThinkClock {...think} /> : <p className="caption">{captionAt(lesson, time)}</p>}
      <div className="controls">
        <button onClick={toggle} aria-label={playing ? "रोकें" : "चलाएँ"}>
          {playing ? "⏸" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={lesson.duration}
          step={0.1}
          value={time}
          style={{ "--p": `${(time / Math.max(1, lesson.duration)) * 100}%` } as React.CSSProperties}
          onChange={(e) => seek(Number(e.target.value))}
        />
        <button className="ask-open" onClick={() => { if (playing) toggle(); setAsking(true); }}>❓ सवाल पूछें</button>
      </div>
      {asking && <ChatPanel lessonId={lesson.id} getTime={() => timeRef.current} onClose={() => setAsking(false)} />}
      {live && !asking && <LiveClass lessonId={lesson.id} getTime={() => timeRef.current} onClose={() => { location.href = "/"; }} />}
    </div>
  );
}

interface IndexEntry { id: string; title: string; duration: number; status: string }

const splitTitle = (t: string) => {
  const [name, tag = ""] = t.split(" · ");
  return { name, tag };
};
const TILES = ["🧪", "🔬", "🌱", "⚗️", "💡", "🧲"];

function LessonList() {
  const [items, setItems] = useState<IndexEntry[] | null>(null);
  useEffect(() => {
    fetch("/lessons/index.json").then((r) => r.json()).then(setItems).catch(() => setItems([]));
  }, []);
  return (
    <div className="home">
      <header className="hero">
        <div className="hero-lamp">🪔</div>
        <h1>नमस्ते! आज क्या सीखेंगे?</h1>
        <p>टीचर से बोलकर, लिखकर या फोटो भेजकर पूछिए</p>
      </header>
      <div className="home-actions">
        <a className="action a1" href="/?chat=1"><span className="ico">💬</span><span><b>टीचर से बात करें</b><small>कोई भी सवाल पूछिए</small></span></a>
        <a className="action a2" href="/?room=new"><span className="ico">🎓</span><span><b>लाइव क्लास</b><small>बोलकर सीखिए</small></span></a>
        <a className="action a3" href="/?join=1"><span className="ico">🔑</span><span><b>कक्षा में जुड़ें</b><small>कोड से दोस्तों के साथ</small></span></a>
      </div>
      <h2 className="section">📚 पाठ</h2>
      {!items ? <p className="empty">लोड हो रहा है…</p> : (
        <div className="lesson-list">
          {items.map((l, i) => {
            const { name, tag } = splitTitle(l.title);
            return (
              <div key={l.id} className="lesson-card">
                <span className="lesson-tile" aria-hidden>{TILES[i % TILES.length]}</span>
                <a href={`/?lesson=${l.id}`} className="lesson-link">
                  <b>{name}</b>
                  <span className="chips">
                    <span className="chip">⏱ {Math.round(l.duration / 60)} मिनट</span>
                    {tag.startsWith("v2") && <span className="chip v2">नया v2</span>}
                    {tag.startsWith("v1") && <span className="chip old">पुराना v1</span>}
                    {l.status === "draft" && <span className="chip draft">समीक्षा बाकी</span>}
                  </span>
                </a>
                <a className="live-link" href={`/?room=new&lesson=${l.id}`}>🎓 लाइव</a>
              </div>
            );
          })}
          {items.length === 0 && <p className="empty">अभी कोई पाठ नहीं है।</p>}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const params = new URLSearchParams(location.search);
  const id = params.get("lesson");
  const [lesson, setLesson] = useState<Lesson | null>(null);
  useEffect(() => {
    if (id) fetch(`/lessons/${id}.json`).then((r) => r.json()).then(setLesson);
  }, [id]);
  if (params.has("teacher")) return <Teacher />;
  if (params.has("room")) return <LiveEntry lessonId={params.get("lesson") ?? ""} joinCode={params.get("room") === "new" ? "" : params.get("room") ?? ""} />;
  if (params.has("join")) return <LiveEntry lessonId="join" joinCode="" />;
  if (!id && params.has("chat")) return <ChatPanel onClose={() => { location.href = "/"; }} />;
  if (!id && params.has("live")) return <LiveClass lessonId="" getTime={() => 0} onClose={() => { location.href = "/"; }} />;
  if (!id) return <LessonList />;
  return lesson ? <Player lesson={lesson} /> : <p>लोड हो रहा है…</p>;
}
