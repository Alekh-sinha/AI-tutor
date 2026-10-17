import { useState } from "react";
import { LiveRoom } from "./LiveRoom";

/** Create a class (as host) or join one with its code; then show the room. Host keys live in sessionStorage only. */
export function LiveEntry({ lessonId, joinCode }: { lessonId: string; joinCode: string }) {
  const [name, setName] = useState(() => { try { return localStorage.getItem("child-name") ?? ""; } catch { return ""; } });
  const [code, setCode] = useState(joinCode);
  const [hostKey, setHostKey] = useState(() => { try { return sessionStorage.getItem(`host-${joinCode}`) ?? ""; } catch { return ""; } });
  const [entered, setEntered] = useState(!!hostKey && !!joinCode);
  const [err, setErr] = useState("");
  const remember = () => { try { localStorage.setItem("child-name", name); } catch { /* private mode */ } };
  const leave = () => { location.href = "/"; };

  const create = async () => {
    remember();
    const r = await fetch("/api/live/rooms", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ lesson_id: lessonId }) });
    if (!r.ok) { setErr((await r.json().catch(() => ({}))).detail ?? "कक्षा नहीं बन पाई।"); return; }
    const j = await r.json();
    try { sessionStorage.setItem(`host-${j.code}`, j.host_key); } catch { /* ignore */ }
    setCode(j.code); setHostKey(j.host_key); setEntered(true);
  };
  const join = async () => {
    remember();
    const r = await fetch(`/api/live/rooms/${code.trim()}`);
    if (!r.ok) { setErr("ऐसी कोई कक्षा नहीं मिली। कोड फिर से देखिए।"); return; }
    setCode(code.trim()); setEntered(true);
  };

  if (entered) return <LiveRoom code={code} name={name} hostKey={hostKey} onLeave={leave} />;
  return (
    <div className="lr lr-center">
      <h1 className="lesson-title">🎓 लाइव क्लास</h1>
      <input className="lr-input" placeholder="आपका नाम" value={name} maxLength={20} onChange={(e) => setName(e.target.value)} />
      {joinCode === "" && lessonId !== "join" ? (
        <button className="lr-btn primary" onClick={create}>{lessonId ? "इस पाठ की लाइव क्लास शुरू करें" : "नई कक्षा बनाएँ (होस्ट)"}</button>
      ) : (
        <>
          <input className="lr-input" inputMode="numeric" placeholder="कक्षा कोड (5 अंक)" value={code} maxLength={5} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <button className="lr-btn primary" disabled={code.length !== 5} onClick={join}>कक्षा में जुड़ें</button>
        </>
      )}
      {err && <p className="t-warn">{err}</p>}
      <a className="lr-link" href="/">← सभी पाठ</a>
    </div>
  );
}
