import { useState } from "react";
import { Icon } from "../ss/icons";
import { LiveRoom } from "./LiveRoom";

/** Create a class (as host) or join one with its code; then show the room. Host keys live in sessionStorage only. */
export function LiveEntry({ lessonId, joinCode }: { lessonId: string; joinCode: string }) {
  const [name, setName] = useState(() => { try { return localStorage.getItem("child-name") ?? ""; } catch { return ""; } });
  const [code, setCode] = useState(joinCode);
  const [hostKey, setHostKey] = useState(() => { try { return sessionStorage.getItem(`host-${joinCode}`) ?? ""; } catch { return ""; } });
  const [entered, setEntered] = useState((!!hostKey && !!joinCode) || (!!joinCode && (() => { try { return !!sessionStorage.getItem(`join-${joinCode}`); } catch { return false; } })()));
  const [err, setErr] = useState("");
  const remember = () => { try { localStorage.setItem("child-name", name); } catch { /* private mode */ } };
  const leave = () => { location.href = "/"; };

  const create = async () => {
    remember();
    const r = await fetch("/api/live/rooms", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ lesson_id: lessonId }) });
    if (!r.ok) { const d = (await r.json().catch(() => ({}))).detail; setErr(typeof d === "string" ? d : d?.message ?? "कक्षा नहीं बन पाई।"); return; }
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
  const hosting = joinCode === "" && lessonId !== "join";
  return (
    <div className="lv lv-center">
      <div className="card panel lv-entry">
        <span className="mark hi">सा</span>
        <h2 className="hi">🎓 लाइव क्लास</h2>
        <input placeholder="आपका नाम" value={name} maxLength={20} onChange={(e) => setName(e.target.value)} />
        {hosting ? (
          <button className="btn pri" onClick={create}>{lessonId ? "इस पाठ की लाइव क्लास शुरू करें" : "नई कक्षा बनाएँ (होस्ट)"}</button>
        ) : (
          <>
            <input inputMode="numeric" placeholder="कक्षा कोड (5 अंक)" value={code} maxLength={5} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            <button className="btn pri" disabled={code.length !== 5} onClick={join}>कक्षा में जुड़ें <Icon n="arrow" sm /></button>
          </>
        )}
        {err && <p className="t-warn">{err}</p>}
        <a className="lv-link" href="/">← वापस</a>
      </div>
    </div>
  );
}
