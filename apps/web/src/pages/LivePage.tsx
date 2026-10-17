import { useState } from "react";
import { Gate } from "../ss/Gate";
import { Icon } from "../ss/icons";
import { readError } from "../ss/api";
import { useMe } from "../ss/auth";

/** Live Classes landing: start a class on a topic (needs an approved account: it uses credit) or join one with a code (children need no account). */
export function LivePage() {
  const { me } = useMe();
  const [topic, setTopic] = useState(() => new URLSearchParams(location.search).get("topic") ?? "");
  const [name, setName] = useState(() => { try { return localStorage.getItem("child-name") ?? ""; } catch { return ""; } });
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true); setErr("");
    const host = (me?.name || "Teacher").split(" ")[0];
    try { localStorage.setItem("child-name", host); } catch { /* private mode */ }
    const r = await fetch("/api/live/rooms", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ lesson_id: "" }) });
    if (!r.ok) { setErr((await readError(r)).message); setBusy(false); return; }
    const j = await r.json();
    try { sessionStorage.setItem(`host-${j.code}`, j.host_key); sessionStorage.setItem(`topic-${j.code}`, topic.trim()); } catch { /* ignore */ }
    location.href = `/?room=${j.code}`;
  };
  const join = async () => {
    setBusy(true); setErr("");
    const r = await fetch(`/api/live/rooms/${code.trim()}`);
    if (!r.ok) { setErr("No class found with that code. Please check it."); setBusy(false); return; }
    try { localStorage.setItem("child-name", name); sessionStorage.setItem(`join-${code.trim()}`, "1"); } catch { /* ignore */ }
    location.href = `/?room=${code.trim()}`;
  };

  return (
    <>
      <h1>Live Classes</h1>
      <p className="sub">Start a class on any topic, or join one with a code.</p>
      <div className="hero">
        <div className="hcard b">
          <div className="art">🎓</div>
          <h2>Start a class</h2>
          <p>Your AI teacher prepares the class with pictures and figures, then teaches live.</p>
          {me?.signed_in && me.status === "active" ? (
            <div className="askbox">
              <input placeholder="What should we learn today?" value={topic} maxLength={200} onChange={(e) => setTopic(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && start()} />
              <button className="btn grn sm" disabled={busy} onClick={start} aria-label="Start the class"><Icon n="arrow" sm /></button>
            </div>
          ) : <p style={{ fontSize: 14 }}>Starting a class needs an approved account (see below).</p>}
        </div>
        <div className="hcard a">
          <div className="art">🔢</div>
          <h2>Join a class</h2>
          <p>Enter the 5-digit code your teacher shared. No account needed.</p>
          <div className="askbox">
            <input placeholder="Your name" style={{ maxWidth: 140 }} maxLength={20} value={name} onChange={(e) => setName(e.target.value)} />
            <input placeholder="Code" inputMode="numeric" maxLength={5} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} onKeyDown={(e) => e.key === "Enter" && code.length === 5 && join()} />
            <button className="btn pri sm" disabled={code.length !== 5 || busy} onClick={join}>Join</button>
          </div>
        </div>
      </div>
      {err && <div className="warn-bar"><Icon n="alert" sm /><span>{err}</span></div>}
      {!(me?.signed_in && me.status === "active") && <Gate title="Sign in to start a class">{null}</Gate>}
      <div className="card panel" style={{ marginTop: 12 }}>
        <h3>How a live class works</h3>
        <div className="step done"><b><Icon n="check" sm /></b>The teacher prepares notes, pictures and figures (about 2–3 minutes).</div>
        <div className="step done"><b><Icon n="check" sm /></b>She talks and shows one screen at a time, then asks questions at the end.</div>
        <div className="step done"><b><Icon n="check" sm /></b>Press and hold “Speak” to answer or to ask your own doubt.</div>
      </div>
    </>
  );
}
