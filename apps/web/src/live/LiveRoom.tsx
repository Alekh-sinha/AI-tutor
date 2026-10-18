import { useState } from "react";
import { Board } from "../player/Board";
import type { BoardElement } from "../player/board";
import { Icon } from "../ss/icons";
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

const COLORS = ["#fb923c", "#10a37f", "#8b5cf6", "#3b82f6", "#ec4899", "#14b8a6"];

/** The streaming live class screen, in the design of the app (same tokens and components as every other page): the teacher talks (voice + captions), writes on the board, asks a question and waits;
 *  children press "speak" to answer or to ask their own doubt. Only buttons that work are shown. */
export function LiveRoom({ code, name, hostKey, onLeave }: { code: string; name: string; hostKey: string; onLeave: () => void }) {
  const r = useLiveRoom(code, name, hostKey);
  const [unlocked, setUnlocked] = useState(false);
  const [topic, setTopic] = useState(() => { try { return sessionStorage.getItem(`topic-${code}`) ?? ""; } catch { return ""; } });
  const [text, setText] = useState("");
  const listen = async () => { await r.unlock(); setUnlocked(true); };
  const n = r.state.members.length;

  if (r.ended) return (
    <div className="lv lv-center card"><h2>{r.ended}</h2><button className="btn pri" onClick={onLeave}><Icon n="back" sm /> वापस</button></div>
  );
  const lastHeard = r.heard[r.heard.length - 1];
  const waitingOther = !!r.state.floor && r.state.floor !== r.me.id && !r.solo;
  return (
    <div className="lv">
      <header className="lv-head">
        <button className="iconbtn" onClick={onLeave} aria-label="बाहर निकलें"><Icon n="back" sm /></button>
        <div className="lv-title"><h2 className="hi">{r.state.started ? "लाइव क्लास" : "कक्षा की तैयारी"}</h2><span>{n} {n === 1 ? "बच्चा" : "बच्चे"} जुड़े हैं</span></div>
        <span className="code" title="यह कोड दूसरे बच्चों को बताइए"><Icon n="users" sm /> {code}</span>
      </header>

      {!r.state.started ? (
        <div className="card panel lv-wait">
          <div className="lv-codecard"><small>यह कोड दोस्तों को बताइए</small><b>{code}</b></div>
          <p className="lv-big hi">{r.me.host ? "सब बच्चे जुड़ जाएँ, फिर कक्षा शुरू कीजिए" : "होस्ट के कक्षा शुरू करने का इंतज़ार…"}</p>
          <div className="lv-people">{r.state.members.map((m, i) => <span className="person" key={m.id}><span className="av" style={{ background: COLORS[i % COLORS.length] }}>{m.name.slice(0, 1)}</span>{m.name}{m.host && <span className="tag">होस्ट</span>}</span>)}</div>
          {r.me.host && (
            <div className="askbox lv-start">
              <input placeholder="आज क्या सीखना है? (खाली छोड़ें तो टीचर बच्चों से पूछेंगी)" value={topic} maxLength={200} onChange={(e) => setTopic(e.target.value)} />
              <button className="btn pri" disabled={!r.connected} onClick={async () => { await listen(); r.start(topic); }}><Icon n="play" sm /> कक्षा शुरू करें</button>
            </div>
          )}
          {!r.me.host && !unlocked && <button className="btn" onClick={listen}>🔊 आवाज़ चालू करें</button>}
        </div>
      ) : (
        <>
          {!unlocked && <button className="btn pri lv-unlock" onClick={listen}>🔊 टीचर को सुनने के लिए यहाँ दबाइए</button>}
          <div className="stage lv-stage">
            <div className="lv-board">
              <div className="lv-teacher">
                <div className="tav">👩‍🏫</div>
                <div><b>दीदी (AI टीचर)</b><div className="lv-state">{r.speaking ? "बोल रही हैं…" : r.status ? "तैयारी कर रही हैं…" : "आपकी बारी का इंतज़ार…"}</div></div>
                {r.speaking && <div className="eq"><i /><i /><i /><i /></div>}
              </div>
              <div className="lv-bwrap">
                <Board state={{ elements: scene(r.board).map((e) => e as unknown as BoardElement), highlighted: null, anims: {} }} time={0} />
              </div>
              {r.question && <div className="qban"><Icon n="msg" sm /> {r.question}</div>}
              <p className="cap">{subtitle(r.caption) || (r.status ? `⏳ ${r.status}` : "…")}</p>
              {r.status && r.caption && <p className="lv-status">⏳ {r.status}</p>}
            </div>

            <div className="lv-side">
              <div className="card panel lv-ctrl">
                {!r.talking ? (
                  <button className="btn pri ptt" disabled={waitingOther} onClick={r.talk}><Icon n="mic" /> बोलिए</button>
                ) : (
                  <div className="lv-talking">
                    <p className="lv-mic">🔴 सुन रही हूँ… बोलिए</p>
                    <button className="btn pri ptt" onClick={r.done}><Icon n="check" /> बोल दिया</button>
                  </div>
                )}
                <div className="chatin">
                  <input placeholder="या यहाँ लिखिए…" value={text} maxLength={300} onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { r.say(text.trim()); setText(""); } }} />
                  <button className="iconbtn pri" aria-label="भेजिए" disabled={!text.trim()} onClick={() => { r.say(text.trim()); setText(""); }}><Icon n="send" sm /></button>
                </div>
                {waitingOther && <p className="lv-hint">🎤 अभी बोल रहे हैं: {r.state.floor_name}</p>}
                {lastHeard && <p className="lv-heard">🧒 {lastHeard.name}: {lastHeard.text}</p>}
                {r.me.host && <button className="btn" onClick={r.next} disabled={r.state.teacher_busy}><Icon n="arrow" sm /> आगे बढ़िए</button>}
              </div>
              <div className="note-bar lv-stuck"><span>ℹ️ अगर क्लास कहीं अटक जाए (टीचर चुप हो जाएँ), तो {r.me.host ? "“आगे बढ़िए” दबाइए" : "होस्ट से “आगे बढ़िए” दबाने को कहिए"}।</span></div>
              {r.state.finished && <div className="note-bar lv-done"><span>🎓 क्लास पूरी हुई — अब आप टीचर से बात करके कोई भी सवाल पूछ सकते हैं।</span></div>}
              {r.state.plan.length > 0 && (
                <div className="card panel lv-plan"><h3>आज की कक्षा</h3>
                  {r.state.plan.map((st, i) => <div className="step" key={i}><b>{i + 1}</b><span className="hi">{st.replace(/^\d+[.)]\s*/, "")}</span></div>)}
                </div>
              )}
              <div className="card panel lv-members"><h3>कक्षा में</h3>
                <div className="person"><span className="av" style={{ background: "#fb923c" }}>दी</span>दीदी <span className="tag" style={{ marginLeft: "auto" }}>टीचर</span></div>
                {r.state.members.map((m, i) => <div className="person" key={m.id}><span className="av" style={{ background: COLORS[(i + 1) % COLORS.length] }}>{m.name.slice(0, 1)}</span>{m.name}{m.id === r.me.id && <span className="tag" style={{ marginLeft: "auto" }}>आप</span>}</div>)}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
