import { useEffect, useState } from "react";
import { photoToBase64, startRecording, type Recorder } from "../chat/media";
import { call, stream, type Job, type Proposal, type View } from "./api";

const IMG = /^!\[(.*?)\]\((.+?)\)\s*$/;

export function Lecture({ view, selected, onSelect }: { view: View; selected: string; onSelect: (s: string) => void }) {
  const blocks = view.markdown.split(/\n\s*\n/).filter((b) => b.trim() && b.trim() !== "---");
  return (
    <div className="t-lecture">
      {blocks.map((b, i) => {
        const m = IMG.exec(b.trim());
        if (m) {
          const name = m[2].replace(/\.(webp|png|jpe?g)$/, "");
          const key = `picture:${name}`;
          return (
            <figure key={i} className={`t-pic ${selected === key ? "sel" : ""}`} onClick={() => onSelect(selected === key ? "" : key)}>
              <img src={`${view.base_url}${name}.webp?v=${view.versions.length}-${view.pending.length}`} alt={m[1]} />
              <figcaption>{name} — {m[1]}</figcaption>
            </figure>
          );
        }
        const head = /^(#+)\s*(.*)/.exec(b.trim());
        if (head) return <h3 key={i} className="t-head">{head[2]}</h3>;
        return <p key={i} className={`t-para ${selected === b ? "sel" : ""}`} onClick={() => onSelect(selected === b ? "" : b)}>{b}</p>;
      })}
    </div>
  );
}

function ProposalCard({ lesson, p, view, done, kind }: { lesson: string; p: Proposal; view: View | null; done: (v?: View, job?: Job) => void; kind: "lecture" | "video" }) {
  const [sure, setSure] = useState(!p.wide);
  const base = kind === "video" ? "/video" : "";
  const act = async (what: "accept" | "reject") => {
    const r = await call<View & Job>("POST", `/lesson/${lesson}${base}/${what}/${p.id}`);
    if (kind === "video") done(undefined, what === "accept" ? (r as Job) : undefined); else done(r as View);
  };
  return (
    <div className="t-prop">
      <p><b>प्रस्तावित बदलाव</b> {p.reply}</p>
      {p.wide && <p className="t-warn">⚠️ यह बड़ा बदलाव है। ध्यान से देखकर ही मंज़ूर कीजिए. <label><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> मैंने देख लिया</label></p>}
      {p.diff.map((d, i) => (
        <div key={i} className="t-diff"><del>{d.before || "(खाली)"}</del><ins>{d.after || "(हटाया गया)"}</ins></div>
      ))}
      {(p.changed_pictures ?? []).map((n) => view && (
        <div key={n} className="t-pics2">
          <figure><img src={`${view.base_url}${n}.webp?old`} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} /><figcaption>पहले</figcaption></figure>
          <figure><img src={`${p.base_url}${n}.webp`} /><figcaption>बाद में: {n}</figcaption></figure>
        </div>
      ))}
      {p.checks.length > 0 && <ul className="t-warn">{p.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>}
      <div className="t-row">
        <button className="t-btn ok" disabled={!sure} onClick={() => act("accept")}>✓ मंज़ूर</button>
        <button className="t-btn" onClick={() => act("reject")}>✗ रद्द</button>
      </div>
    </div>
  );
}

export function Editor({ lesson, selected, view, refresh, kind = "lecture" }: { lesson: string; selected: string; view: View | null; refresh: (v?: View, job?: Job) => void; kind?: "lecture" | "video" }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [msg, setMsg] = useState("");
  const [prop, setProp] = useState<Proposal | null>(null);
  const [rec, setRec] = useState<Recorder | null>(null);

  const send = async (extra: { audio_b64?: string; image_b64?: string } = {}) => {
    if (busy || (!text.trim() && !extra.audio_b64 && !extra.image_b64)) return;
    setBusy(true); setMsg(""); setProp(null); setStatus("सोच रहा हूँ…");
    try {
      await stream(`/lesson/${lesson}${kind === "video" ? "/video" : ""}/edit`, { instruction: text, selection: selected, ...extra }, (e) => {
        if (e.type === "thinking") setStatus(e.text);
        else if (e.type === "question") setMsg(`❓ ${e.text}`);
        else if (e.type === "reply") setMsg(e.text);
        else if (e.type === "error") setMsg(`⚠️ ${e.text}`);
        else if (e.type === "proposal") setProp(e as unknown as Proposal);
      });
      setText("");
    } catch (err) { setMsg(`⚠️ ${err instanceof Error ? err.message : "error"}`); }
    setBusy(false); setStatus("");
  };
  const mic = async () => {
    if (rec) { const b = await rec.stop(); setRec(null); void send({ audio_b64: b }); return; }
    try { setRec(await startRecording()); } catch { alert("माइक की अनुमति नहीं मिली।"); }
  };
  const photo = async (f?: File) => { if (f) void send({ image_b64: await photoToBase64(f) }); };

  return (
    <div className="t-edit">
      {selected && <p className="t-sel">चुना हुआ: {selected.startsWith("picture:") ? selected : selected.slice(0, 80) + "…"}</p>}
      {busy && <p className="ask-status">⏳ {status}</p>}
      {msg && <p className="t-msg">{msg}</p>}
      {prop && <ProposalCard lesson={lesson} p={prop} view={view} kind={kind} done={(v, j) => { setProp(null); refresh(v, j); }} />}
      <textarea value={text} rows={3} disabled={busy} placeholder="क्या बदलना है? (हिंदी या English) — पहले पाठ या चित्र पर क्लिक करके चुन सकते हैं"
        onChange={(e) => setText(e.target.value)} />
      <div className="t-row">
        <button className={`t-btn ${rec ? "rec" : ""}`} disabled={busy} onClick={mic}>{rec ? "⏹ रोकें" : "🎤 बोलकर"}</button>
        {kind === "lecture" && <label className="t-btn">📷<input type="file" accept="image/*" hidden onChange={(e) => void photo(e.target.files?.[0])} /></label>}
        <button className="t-btn ok" disabled={busy || !text.trim()} onClick={() => send()}>भेजें</button>
      </div>
    </div>
  );
}

interface VLine { i: number; text: string; cues: { kind: string; id: string | null; text: string; target: string | null }[] }

export function VideoView({ lesson, selected, onSelect, busy }: { lesson: string; selected: string; onSelect: (s: string) => void; busy: boolean }) {
  const [data, setData] = useState<{ public_id: string; draft_id: string; publish: { live: boolean; draft_ready: boolean }; lines: VLine[]; checks: string[]; versions: number[] } | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { if (!busy) call<typeof data>("GET", `/lesson/${lesson}/video`).then(setData).catch((e) => setErr(String(e.message))); }, [lesson, busy]);
  if (err) return <p className="t-warn">इस पाठ का वीडियो अभी नहीं बना (पहले बनाइए)। {err.slice(0, 120)}</p>;
  if (!data) return <p>लोड हो रहा है…</p>;
  const icon: Record<string, string> = { image: "🖼️", note: "📝", choice: "❓", anim: "✨", clear: "🧹", hide: "·" };
  return (
    <div className="t-lecture">
      <p><a href={`/?lesson=${data.publish.live ? data.draft_id : data.public_id}`} target="_blank" rel="noreferrer">▶ {data.publish.live ? "ड्राफ़्ट वीडियो देखें (छात्र अभी पुराना देख रहे हैं)" : "वीडियो देखें"}</a> · पिछला बदलाव वापस: <button className="t-btn" disabled={!data.versions.length || busy} onClick={async () => { await call("POST", `/lesson/${lesson}/video/undo`); location.reload(); }}>↶ ({data.versions.length})</button></p>
      {data.checks.length > 0 && <ul className="t-warn">{data.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>}
      {data.lines.map((l) => (
        <p key={l.i} className={`t-para ${selected === `line:${l.i}` ? "sel" : ""}`} onClick={() => onSelect(selected === `line:${l.i}` ? "" : `line:${l.i}`)}>
          <small>[{l.i}]</small> {l.text}
          <br /><small style={{ color: "#777" }}>{l.cues.filter((c) => c.kind !== "hide").map((c) => `${icon[c.kind] ?? ""}${c.kind === "clear" ? "नया दृश्य" : c.text.slice(0, 28)}`).join("  ")}</small>
        </p>
      ))}
    </div>
  );
}

export function JobBox({ job, onDone }: { job: Job; onDone: () => void }) {
  const [j, setJ] = useState<Job>(job);
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const n = await call<Job>("GET", `/jobs/${job.id}`);
        setJ(n);
        if (n.status !== "running") { clearInterval(t); onDone(); }
      } catch { /* server restarting: keep polling */ }
    }, 4000);
    return () => clearInterval(t);
  }, [job.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const lessons = j.result?.lessons;
  const used = j.result?.pages_used, total = j.result?.pages_total;
  const cut = typeof used === "number" && typeof total === "number" && used < total ? ` ⚠️ The PDF is very long (${total} pages): only the first ${used} pages were used. Please upload one chapter at a time for best results.` : "";
  const done = typeof j.result?.public_id === "string" ? "✓ The video is ready — watch it with the button below."
    : typeof lessons === "number" ? `✓ Chapter read: ${lessons} lessons planned.${cut}  The videos are not made yet — press Generate next to a lesson (each video takes about 20–30 minutes).`
    : "✓ Done";
  const eta = j.label.includes("/") ? "about 20–30 minutes" : "a minute or two";
  return (
    <div className="t-box">
      <b>{j.label}</b>
      {j.status === "running"
        ? <div className="job-wait"><span className="spin" aria-hidden /><p>Your result will be generated soon. Meanwhile you can explore the other sections. It takes {eta}.</p></div>
        : <p>{j.status === "done" ? done : `⚠️ ${j.error}`}</p>}
      {j.status === "done" && typeof j.result?.public_id === "string" && <p><a className="t-btn ok" href={`/?lesson=${j.result.public_id}`} target="_blank" rel="noreferrer">▶ Watch the video</a></p>}
    </div>
  );
}

