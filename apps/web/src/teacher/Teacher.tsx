import { useEffect, useState } from "react";
import { photoToBase64, startRecording, type Recorder } from "../chat/media";
import { call, getToken, setChapter, setToken, stream, uploadChapter, type ChapterInfo, type Job, type Proposal, type View } from "./api";

const IMG = /^!\[(.*?)\]\((.+?)\)\s*$/;

function Lecture({ view, selected, onSelect }: { view: View; selected: string; onSelect: (s: string) => void }) {
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

function Editor({ lesson, selected, view, refresh, kind = "lecture" }: { lesson: string; selected: string; view: View | null; refresh: (v?: View, job?: Job) => void; kind?: "lecture" | "video" }) {
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

function VideoView({ lesson, selected, onSelect, busy }: { lesson: string; selected: string; onSelect: (s: string) => void; busy: boolean }) {
  const [data, setData] = useState<{ public_id: string; lines: VLine[]; checks: string[]; versions: number[] } | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { if (!busy) call<typeof data>("GET", `/lesson/${lesson}/video`).then(setData).catch((e) => setErr(String(e.message))); }, [lesson, busy]);
  if (err) return <p className="t-warn">इस पाठ का वीडियो अभी नहीं बना (पहले बनाइए)। {err.slice(0, 120)}</p>;
  if (!data) return <p>लोड हो रहा है…</p>;
  const icon: Record<string, string> = { image: "🖼️", note: "📝", choice: "❓", anim: "✨", clear: "🧹", hide: "·" };
  return (
    <div className="t-lecture">
      <p><a href={`/?lesson=${data.public_id}`} target="_blank" rel="noreferrer">▶ वीडियो देखें</a> · पिछला बदलाव वापस: <button className="t-btn" disabled={!data.versions.length || busy} onClick={async () => { await call("POST", `/lesson/${lesson}/video/undo`); location.reload(); }}>↶ ({data.versions.length})</button></p>
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

function Panel({ lesson }: { lesson: string }) {
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState("");
  const [review, setReview] = useState<string[] | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [approve, setApprove] = useState(false);
  const [pub, setPub] = useState("");
  const [tab, setTab] = useState<"lecture" | "video">("lecture");
  const [vjob, setVjob] = useState<Job | null>(null);
  const refresh = (v?: View) => (v ? Promise.resolve(setView(v)) : call<View>("GET", `/lesson/${lesson}`).then(setView));
  useEffect(() => { void refresh(); }, [lesson]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!view) return <p>लोड हो रहा है…</p>;

  const runReview = async () => {
    setReviewing(true);
    try { setReview((await call<{ findings: string[] }>("POST", `/lesson/${lesson}/review`)).findings); } catch (e) { setReview([String(e)]); }
    setReviewing(false);
  };
  const publish = async () => {
    setPub("चल रहा है… (वीडियो बन रहा है, कुछ मिनट लगेंगे)");
    try {
      await call("POST", `/lesson/${lesson}/publish`, { approved_by_teacher: approve });
      for (;;) {
        await new Promise((r) => setTimeout(r, 5000));
        const s = await call<{ status: string; error?: string }>("GET", `/lesson/${lesson}/publish-status`);
        if (s.status === "done") { setPub(`✓ प्रकाशित हो गया (/?lesson=${lesson}-v2)`); break; }
        if (s.status === "failed") { setPub(`⚠️ ${s.error}`); break; }
      }
    } catch (e) { setPub(`⚠️ ${e instanceof Error ? e.message : e}`); }
  };

  return (
    <div>
    <div className="t-row" style={{ margin: "8px 0" }}>
      <button className={`t-btn ${tab === "lecture" ? "ok" : ""}`} onClick={() => { setTab("lecture"); setSelected(""); }}>📖 पाठ (लेक्चर)</button>
      <button className={`t-btn ${tab === "video" ? "ok" : ""}`} onClick={() => { setTab("video"); setSelected(""); }}>🎬 वीडियो</button>
    </div>
    {vjob && <JobBox key={vjob.id} job={vjob} onDone={() => setVjob(null)} />}
    <div className="t-grid">
      <div>
        {tab === "lecture" ? <Lecture view={view} selected={selected} onSelect={setSelected} /> : <VideoView lesson={lesson} selected={selected} onSelect={setSelected} busy={!!vjob} />}
      </div>
      <aside className="t-side">
        <Editor key={tab} lesson={lesson} selected={selected} view={view} kind={tab} refresh={(v, j) => { if (j) setVjob(j); if (v) void refresh(v); }} />
        <div className="t-box">
          <b>जाँच (कोड)</b>
          {view.checks.length === 0 ? <p>✓ सब ठीक</p> : <ul className="t-warn">{view.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          {view.checks.some((c) => c.includes("not used in the lecture")) && (
            <button className="t-btn" onClick={async () => refresh(await call<View>("POST", `/lesson/${lesson}/archive-unused`))}>🗄 बिना इस्तेमाल की तस्वीरें अलग रखें</button>
          )}
          <div className="t-row">
            <button className="t-btn" disabled={reviewing} onClick={runReview}>{reviewing ? "समीक्षा चल रही है…" : "🔍 पूरी समीक्षा (कुछ मिनट)"}</button>
            <button className="t-btn" disabled={view.versions.length === 0} onClick={async () => refresh(await call<View>("POST", `/lesson/${lesson}/undo`))}>↶ पिछला बदलाव वापस ({view.versions.length})</button>
          </div>
          {review && (review.length === 0 ? <p>✓ समीक्षकों को कुछ नहीं मिला</p> : <ul className="t-warn">{review.map((c, i) => <li key={i}>{c}</li>)}</ul>)}
        </div>
        <div className="t-box">
          <b>प्रकाशित करें</b>
          <label><input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} /> मैंने पूरा पाठ देख लिया है और मंज़ूर करता/करती हूँ</label>
          <button className="t-btn ok" disabled={!approve || view.checks.length > 0 || view.pending.length > 0 || pub.startsWith("चल")} onClick={publish}>वीडियो बनाएँ और प्रकाशित करें</button>
          {pub && <p>{pub}</p>}
        </div>
      </aside>
    </div>
    </div>
  );
}

function JobBox({ job, onDone }: { job: Job; onDone: () => void }) {
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
  const mins = Math.floor(j.elapsed / 60);
  const lessons = j.result?.lessons;
  const done = typeof j.result?.public_id === "string" ? "✓ वीडियो बन गया (नीचे बटन से देखिए)"
    : typeof lessons === "number" ? `✓ अध्याय पढ़ लिया: ${lessons} पाठ तय हुए। वीडियो अभी नहीं बने — हर पाठ के आगे "⚙ वीडियो बनाएँ" दबाइए (हर वीडियो में लगभग 20-30 मिनट लगते हैं)।`
    : "✓ पूरा हुआ";
  return (
    <div className="t-box">
      <b>{j.label}</b>
      <p>{j.status === "running" ? `⏳ ${j.stage} — ${mins} मिनट` : j.status === "done" ? done : `⚠️ ${j.error}`}</p>
      {j.status === "done" && typeof j.result?.public_id === "string" && <p><a className="t-btn ok" href={`/?lesson=${j.result.public_id}`} target="_blank" rel="noreferrer">▶ वीडियो देखें</a></p>}
    </div>
  );
}

function Chapters({ onOpen }: { onOpen: (chapter: string, lesson: string) => void }) {
  const [chapters, setChapters] = useState<ChapterInfo[] | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [msg, setMsg] = useState("");
  const [up, setUp] = useState({ id: "", book: "" });
  const load = () => call<ChapterInfo[]>("GET", "/chapters").then(setChapters).catch((e) => setMsg(String(e.message)));
  useEffect(() => {
    const refresh = () => {
      void load();
      // a job started before a page refresh (or by another tab) is shown again; the list refreshes itself while it runs
      void call<Job[]>("GET", "/jobs").then((js) => setJob((cur) => (cur && cur.status === "running" ? cur : js[0] ?? cur))).catch(() => undefined);
    };
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const generate = async (c: string, l: string) => {
    setChapter(c); setMsg("");
    try { setJob(await call<Job>("POST", `/lesson/${l}/generate`)); } catch (e) { setMsg(`⚠️ ${e instanceof Error ? e.message : e}`); }
  };
  const upload = async (f?: File) => {
    if (!f || !up.id || !up.book) { setMsg("पहले अध्याय का नाम (अंग्रेज़ी, बिना स्पेस) और किताब का नाम लिखिए।"); return; }
    try { setJob(await uploadChapter(up.id, up.book, f)); } catch (e) { setMsg(`⚠️ ${e instanceof Error ? e.message : e}`); }
  };
  if (!chapters) return <p>{msg || "लोड हो रहा है…"}</p>;
  return (
    <div>
      {msg && <p className="t-warn">{msg}</p>}
      {job && <JobBox key={job.id} job={job} onDone={() => void load()} />}
      {chapters.map((c) => (
        <div key={c.id} className="t-box" style={{ marginBottom: 12 }}>
          <b>{c.book} <small>({c.id})</small></b>
          {c.lessons.map((l) => (
            <div key={l.id} className="t-row t-lrow">
              <span className="t-ltitle">{l.title}</span>
              {l.has_lecture ? <button className="t-btn ok" onClick={() => onOpen(c.id, l.id)}>✎ संपादित करें{l.pending ? ` (${l.pending})` : ""}</button>
                : <button className="t-btn" disabled={job?.status === "running"} onClick={() => generate(c.id, l.id)}>⚙ वीडियो बनाएँ</button>}
              {l.has_video && <a className="t-btn" href={`/?lesson=${l.public_id}`} target="_blank" rel="noreferrer">▶ देखें</a>}
            </div>
          ))}
        </div>
      ))}
      <div className="t-box">
        <b>नई किताब / अध्याय (PDF)</b>
        <div className="t-row">
          <input placeholder="अध्याय का नाम (जैसे ch7)" value={up.id} onChange={(e) => setUp({ ...up, id: e.target.value })} />
          <input placeholder="किताब का नाम" value={up.book} onChange={(e) => setUp({ ...up, book: e.target.value })} />
          <label className="t-btn">📄 PDF चुनें<input type="file" accept="application/pdf" hidden onChange={(e) => void upload(e.target.files?.[0])} /></label>
        </div>
      </div>
    </div>
  );
}

export function Teacher() {
  const [needToken, setNeedToken] = useState(false);
  const [open, setOpen] = useState<{ chapter: string; lesson: string } | null>(null);
  useEffect(() => { call("GET", "/chapters").catch((e) => e.message === "401" && setNeedToken(true)); }, []);
  if (needToken) return <div className="t-page"><p>शिक्षक कोड डालिए</p><input type="password" onKeyDown={(e) => { if (e.key === "Enter") { setToken((e.target as HTMLInputElement).value); location.reload(); } }} /></div>;
  return (
    <div className="t-page">
      <h1 className="lesson-title">शिक्षक डैशबोर्ड {getToken() ? "🔒" : ""}</h1>
      {open ? (
        <>
          <button className="t-btn" onClick={() => setOpen(null)}>← सभी पाठ</button>
          <Panel key={`${open.chapter}/${open.lesson}`} lesson={open.lesson} />
        </>
      ) : <Chapters onOpen={(chapter, lesson) => { setChapter(chapter); setOpen({ chapter, lesson }); }} />}
    </div>
  );
}
