import { useState } from "react";
import { Board } from "../player/Board";
import type { BoardElement } from "../player/board";
import { useLiveRoom, type BoardEl } from "./useLiveRoom";

/** The board is exactly what the server's board holds (ONE screen: the teacher's show_screen replaces it): heading first, then the picture or figure, then the key words. */
function scene(board: BoardEl[]): BoardEl[] {
  const isHead = (e: BoardEl) => e.type === "note" && e.style === "heading";
  const isVisual = (e: BoardEl) => e.type === "image" || e.type === "figure";
  return [...board.filter(isHead), ...board.filter(isVisual), ...board.filter((e) => !isHead(e) && !isVisual(e))];
}

/** Subtitle: only the sentence being spoken now, never the whole script. */
function subtitle(text: string): string {
  const parts = text.split(/(?<=[.?!।])\s*/).filter((x) => x.trim());
  return parts.slice(-1).join(" ").slice(-160);
}

/** The streaming live class screen: the teacher talks (voice + captions), writes on the board, asks a question and waits; children raise hands, the child with the floor answers by voice or text. */
export function LiveRoom({ code, name, hostKey, onLeave }: { code: string; name: string; hostKey: string; onLeave: () => void }) {
  const r = useLiveRoom(code, name, hostKey);
  const [unlocked, setUnlocked] = useState(false);
  const [topic, setTopic] = useState(() => { try { return sessionStorage.getItem(`topic-${code}`) ?? ""; } catch { return ""; } });
  const [text, setText] = useState("");
    const listen = async () => { await r.unlock(); setUnlocked(true); };

  if (r.ended) return (
    <div className="lr lr-center"><h2>{r.ended}</h2><button className="lr-btn primary" onClick={onLeave}>← वापस</button></div>
  );
  return (
    <div className="lr">
      <header className="lr-top">
        <span className="lr-code" title="यह कोड दूसरे बच्चों को बताइए">कक्षा कोड <b>{code}</b></span>
        <span className="lr-people">👥 {r.state.members.length}</span>
        <button className="lr-x" onClick={onLeave} aria-label="बाहर निकलें">✕</button>
      </header>

      {!r.state.started ? (
        <div className="lr-wait">
          <div className="lr-codecard"><small>यह कोड दोस्तों को बताइए</small><b>{code}</b></div>
          <p className="lr-big">{r.me.host ? "सब बच्चे जुड़ जाएँ, फिर कक्षा शुरू कीजिए" : "होस्ट के कक्षा शुरू करने का इंतज़ार…"}</p>
          <ul className="lr-members">{r.state.members.map((m) => <li key={m.id}>{m.host ? "👩‍🏫" : "🧒"} {m.name}</li>)}</ul>
          {r.me.host && (
            <>
              <input className="lr-input" placeholder="आज क्या सीखना है? (खाली छोड़ें तो टीचर बच्चों से पूछेंगी)" value={topic} maxLength={200} onChange={(e) => setTopic(e.target.value)} />
              <button className="lr-btn primary" disabled={!r.connected} onClick={async () => { await listen(); r.start(topic); }}>▶ कक्षा शुरू करें</button>
            </>
          )}
          {!r.me.host && !unlocked && <button className="lr-btn" onClick={listen}>🔊 आवाज़ चालू करें</button>}
        </div>
      ) : (
        <>
          {!unlocked && <button className="lr-btn primary lr-unlock" onClick={listen}>🔊 टीचर को सुनने के लिए यहाँ दबाइए</button>}
          {r.state.plan.length > 0 && <ol className="lr-steps">{r.state.plan.map((st, i) => <li key={i}>{st.replace(/^\d+[.)]\s*/, "")}</li>)}</ol>}
          <div className="lr-stage">
            <div className={`lr-teacher ${r.speaking ? "talking" : ""}`} aria-hidden>👩‍🏫{r.speaking && <span className="lr-wave"><i /><i /><i /><i /></span>}</div>
            <div className="lr-board">
              <Board state={{ elements: scene(r.board).map((e) => e as unknown as BoardElement), highlighted: null, anims: {} }} time={0} />
            </div>
          </div>
          {r.question && <p className="lr-question">❓ {r.question}</p>}
          <p className="lr-caption">{subtitle(r.caption) || (r.status ? `⏳ ${r.status}` : "…")}</p>
          {r.status && r.caption && <p className="lr-status">⏳ {r.status}</p>}
          {r.heard.length > 0 && <p className="lr-heard">🧒 {r.heard[r.heard.length - 1].name}: {r.heard[r.heard.length - 1].text}</p>}
          {r.state.finished && <p className="lr-done">🎓 क्लास पूरी हुई — अब आप टीचर से बात करके कोई भी सवाल पूछ सकते हैं।</p>}
          <div className="lr-controls">
            <div className="lr-mine">
              {!r.talking ? (
                <button className="lr-btn primary lr-talk" disabled={!!r.state.floor && r.state.floor !== r.me.id && !r.solo} onClick={r.talk}>🎤 बोलिए</button>
              ) : (
                <div className="lr-row">
                  <p className="lr-mic">🔴 सुन रही हूँ… बोलिए</p>
                  <button className="lr-btn primary" onClick={r.done}>✔ बोल दिया</button>
                </div>
              )}
              <input className="lr-input" placeholder="या यहाँ लिखिए…" value={text} maxLength={300} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { r.say(text.trim()); setText(""); } }} />
            </div>
            {r.state.floor && r.state.floor !== r.me.id && !r.solo && <p className="lr-floor">🎤 अभी बोल रहे हैं: {r.state.floor_name}</p>}
            {r.me.host && (
              <div className="lr-host">
                <button className="lr-btn" onClick={r.next} disabled={r.state.teacher_busy}>▶ आगे बढ़िए</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
