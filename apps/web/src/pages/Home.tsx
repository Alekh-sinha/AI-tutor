import { useState } from "react";
import { Icon } from "../ss/icons";
import { LessonsTable, useLessons } from "./Lessons";

export function Home() {
  const [topic, setTopic] = useState("");
  const items = useLessons();
  const go = () => { location.href = `/live${topic.trim() ? `?topic=${encodeURIComponent(topic.trim())}` : ""}`; };
  return (
    <>
      <h1>Welcome to Seekho Saathi</h1>
      <p className="sub">Learn, create and explore with the help of AI.</p>
      <div className="hero">
        <div className="hcard a">
          <div className="art">📄▶️</div>
          <h2>Create a lesson<br />from your material</h2>
          <p>Upload a PDF or a book chapter and we will make a clear, engaging Hindi video lesson for you.</p>
          <a className="btn pri" href="/teacher">
            <Icon n="upload" sm />Upload and create <Icon n="arrow" sm />
          </a>
        </div>
        <div className="hcard b">
          <div className="art">💬🎓</div>
          <h2><a href="/live">Live Classes</a></h2>
          <p>Ask any topic and your AI teacher will explain it in a live, interactive class.</p>
          <div className="askbox">
            <input placeholder="e.g. Why do things float? Fractions, Solar system…" value={topic} onChange={(e) => setTopic(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} />
            <button className="btn grn sm" onClick={go} aria-label="Open live classes"><Icon n="arrow" sm /></button>
          </div>
        </div>
      </div>
      <div className="note-bar" style={{ alignItems: "center" }}>
        <Icon n="msg" sm /><span>Have a quick question? Type, speak or send a photo to the teacher.</span>
        <a className="btn sm" style={{ marginLeft: "auto" }} href="/?chat=1">Ask the teacher</a>
      </div>
      <div className="row between" style={{ margin: "26px 0 14px" }}><h2>Your lessons</h2><a href="/lessons" style={{ color: "var(--brand)", fontWeight: 600 }}>View all →</a></div>
      {items ? <LessonsTable items={items.slice(0, 4)} /> : <p className="sub">Loading…</p>}
    </>
  );
}
