import { useRef, useState } from "react";
import type { Lesson } from "../../../../packages/lesson-schema/lesson";
import { ChatPanel } from "../chat/ChatPanel";
import { LiveClass } from "../chat/LiveClass";
import { Board } from "../player/Board";
import { boardAt, captionAt, thinkingAt } from "../player/board";
import { Ended } from "../player/Ended";
import { ThinkClock } from "../player/ThinkClock";
import { usePlayer } from "../player/usePlayer";

export function Player({ lesson }: { lesson: Lesson }) {
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
        <a className="back" href="/lessons" aria-label="सभी पाठ">←</a>
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

