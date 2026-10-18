import { useCallback, useEffect, useState } from "react";
import { Gate } from "../ss/Gate";
import { Icon } from "../ss/icons";
import { call, setChapter, uploadChapter, type ChapterInfo, type Job, type View } from "./api";
import { Editor, JobBox, Lecture, VideoView } from "./parts";

type Lesson = ChapterInfo["lessons"][number];

/** The page address holds where you are (?tab=&chapter=&lesson=&w=), so a reload or a shared link returns to the same place. */
function useNav() {
  const read = () => Object.fromEntries(new URLSearchParams(location.search));
  const [q, setQ] = useState<Record<string, string>>(read);
  useEffect(() => { const f = () => setQ(read()); window.addEventListener("popstate", f); return () => window.removeEventListener("popstate", f); }, []);
  const go = (next: Record<string, string>) => {
    const sp = new URLSearchParams(next);
    history.pushState(null, "", `${location.pathname}${sp.toString() ? `?${sp}` : ""}`);
    setQ(read());
    window.scrollTo(0, 0);
  };
  return { q, go };
}

function statusOf(l: Lesson, job?: Job) {
  if (job?.status === "running") return { cls: "gen", text: "Generating" };
  if (!l.has_lecture) return { cls: "draft", text: "Not generated" };
  if (l.live) return { cls: "ready", text: `Published · v${l.version}` };
  return { cls: "rev", text: "In review" };
}

function Chapters({ chapters, jobs, open, onJob, onChange }: { chapters: ChapterInfo[]; jobs: Job[]; open: (c: string) => void; onJob: (j: Job) => void; onChange: () => void }) {
  const [book, setBook] = useState("");
  const [msg, setMsg] = useState("");
  const upload = async (f?: File) => {
    if (!f) return;
    if (!book.trim()) { setMsg("First write the book and chapter name, for example “Class 6 Science, Ch. 7”."); return; }
    setMsg("");
    try { onJob(await uploadChapter(`ch${Date.now() % 1000000}`, book.trim(), f)); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <>
      <div className="drop" style={{ padding: 24, marginBottom: 22 }}>
        <div className="row" style={{ justifyContent: "center", flexWrap: "wrap" }}>
          <div style={{ fontSize: 30 }}>📄</div>
          <div style={{ textAlign: "left" }}><b>Upload a chapter PDF</b><div style={{ color: "var(--muted)" }}>We read the chapter and plan the lessons (a few minutes). Each video then takes about 20–30 minutes.</div></div>
          <input className="t-input" placeholder="Book and chapter name" value={book} onChange={(e) => setBook(e.target.value)} />
          <label className="btn pri"><Icon n="upload" sm />Choose PDF<input type="file" accept="application/pdf" hidden onChange={(e) => void upload(e.target.files?.[0])} /></label>
        </div>
        {msg && <p className="t-warn">{msg}</p>}
      </div>
      <h2 style={{ marginBottom: 14 }}>Chapters</h2>
      {chapters.length === 0 ? <div className="card panel"><p className="sub" style={{ margin: 0 }}>No chapters yet. Upload a PDF above.</p></div> : (
        <div className="card" style={{ overflow: "hidden" }}>
          <table className="tbl">
            <thead><tr><th>Chapter</th><th>Lessons</th><th>Progress</th><th /></tr></thead>
            <tbody>
              {chapters.map((c) => {
                const live = c.lessons.filter((l) => l.live).length, review = c.lessons.filter((l) => l.has_lecture && !l.live).length;
                const gen = c.lessons.filter((l) => jobs.some((j) => j.status === "running" && j.label === `${c.id}/${l.id}`)).length;
                return (
                  <tr key={c.id}>
                    <td className="c-ttl"><div className="ttl"><div className="thumb t1">📘</div><div><b>{c.book}</b><small>{c.id}</small></div></div></td>
                    <td className="c-type">{c.lessons.length} lessons</td>
                    <td className="c-st">{live} published · {review} in review · {gen} generating</td>
                    <td className="c-act"><button className="btn out sm" onClick={() => { onChange(); open(c.id); }}>Open</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ChapterDetail({ c, jobs, nav, onJob, reload }: { c: ChapterInfo; jobs: Job[]; nav: (n: Record<string, string>) => void; onJob: (j: Job) => void; reload: () => void }) {
  const [msg, setMsg] = useState("");
  const generate = async (l: Lesson) => {
    setChapter(c.id); setMsg("");
    try { onJob(await call<Job>("POST", `/lesson/${l.id}/generate`)); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  const count = (f: (l: Lesson) => boolean) => c.lessons.filter(f).length;
  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="iconbtn" onClick={() => nav({})} aria-label="Back"><Icon n="back" sm /></button>
        <div><h2>{c.book}</h2><span style={{ color: "var(--muted)", fontSize: 14 }}>{c.lessons.length} lessons</span></div>
      </div>
      <div className="stat stat4">
        <div className="card"><b>{count((l) => jobs.some((j) => j.status === "running" && j.label === `${c.id}/${l.id}`))}</b><span>Generating</span></div>
        <div className="card"><b>{count((l) => l.has_lecture && !l.live)}</b><span>In review</span></div>
        <div className="card"><b>{count((l) => l.live)}</b><span>Published</span></div>
        <div className="card"><b>{count((l) => l.draft)}</b><span>With draft changes</span></div>
      </div>
      {msg && <div className="warn-bar"><Icon n="alert" sm /><span>{msg}</span></div>}
      <div className="card" style={{ overflow: "hidden" }}>
        <table className="tbl">
          <thead><tr><th>Lesson</th><th>Status</th><th>Edit</th></tr></thead>
          <tbody>
            {c.lessons.map((l, i) => {
              const job = jobs.find((j) => j.label === `${c.id}/${l.id}`);
              const st = statusOf(l, job);
              const go = (w: string) => nav({ chapter: c.id, lesson: l.id, w });
              return (
                <tr key={l.id}>
                  <td className="c-ttl"><div className="ttl"><div className={`thumb t${(i % 4) + 1}`}>{["🏺", "🪟", "🧺", "🧂"][i % 4]}</div><div><b className="hi">{i + 1}. {l.title}</b>{job?.status === "running" && <div className="job-wait mini"><span className="spin sm" aria-hidden /><small>Generating — about 20–30 minutes. You can explore other sections meanwhile.</small></div>}</div></div></td>
                  <td className="c-st"><span className={`chip ${st.cls}`}>{st.text}</span>{l.draft && <div style={{ marginTop: 5 }}><span className="chip rev" style={{ fontSize: 12, padding: "2px 9px" }}>Draft v{l.version + 1} · not live</span></div>}</td>
                  <td className="c-act">
                    {l.has_lecture ? (
                      <div className="row" style={{ flexWrap: "wrap" }}>
                        <button className="btn out sm" onClick={() => go("lecture")}><Icon n="edit" sm />Lecture</button>
                        <button className="btn out sm" onClick={() => go("video")}><Icon n="video" sm />Video</button>
                        <button className="btn sm" onClick={() => go("publish")}>{l.live ? (l.draft ? "Publish changes" : "Manage") : "Publish"}</button>
                      </div>
                    ) : job?.status === "running" ? <button className="btn sm" disabled>Generating…</button> : <button className="btn pri sm" disabled={jobs.some((j) => j.status === "running")} onClick={() => generate(l)}>Generate lesson</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="sub" style={{ marginTop: 10, fontSize: 13 }}>Generating a lesson takes about 20–30 minutes and uses roughly $3 of credit. You can leave this page; the lesson appears here when it is ready.</p>
      <button className="btn sm" style={{ display: "none" }} onClick={reload} />
    </>
  );
}

function Workspace({ c, l, w, nav, reload }: { c: ChapterInfo; l: Lesson; w: string; nav: (n: Record<string, string>) => void; reload: () => void }) {
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState("");
  const [vjob, setVjob] = useState<Job | null>(null);
  const [review, setReview] = useState<string[] | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [approve, setApprove] = useState(false);
  const [pub, setPub] = useState("");
  const load = useCallback(async () => { setChapter(c.id); setView(await call<View>("GET", `/lesson/${l.id}`)); reload(); }, [c.id, l.id, reload]);
  useEffect(() => { void load(); }, [load]);
  if (!view) return <p className="sub">Loading…</p>;
  const p = view.publish;
  const tab = w === "video" || w === "publish" ? w : "lecture";
  const set = (v?: View) => (v ? (setView(v), reload()) : load());

  const runReview = async () => {
    setReviewing(true);
    try { setReview((await call<{ findings: string[] }>("POST", `/lesson/${l.id}/review`)).findings); } catch (e) { setReview([e instanceof Error ? e.message : String(e)]); }
    setReviewing(false);
  };
  const poll = async () => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 5000));
      const s = await call<{ status: string; error?: string }>("GET", `/lesson/${l.id}/publish-status`);
      if (s.status === "done") { setPub("✓ Published."); await load(); return; }
      if (s.status === "failed") { setPub(`⚠️ ${s.error}`); return; }
    }
  };
  const publish = async () => {
    setPub("Publishing… the video is being rebuilt, this takes a few minutes.");
    try { await call("POST", `/lesson/${l.id}/publish`, { approved_by_teacher: approve }); await poll(); } catch (e) { setPub(`⚠️ ${e instanceof Error ? e.message : e}`); }
  };
  const publishVideoDraft = async () => {
    try { await call("POST", `/lesson/${l.id}/video/publish-draft`); setPub("✓ Video changes are now live."); await load(); } catch (e) { setPub(`⚠️ ${e instanceof Error ? e.message : e}`); }
  };
  const discard = async () => { await call("POST", `/lesson/${l.id}/video/discard-draft`); setPub("Draft discarded."); await load(); };

  const checksOk = view.checks.length === 0 && view.pending.length === 0;
  const lectureNotice = p.live && <div className="note-bar"><Icon n="alert" sm /><span>Students are watching <b>v{p.version}</b>. Your edits go to a <b>draft v{p.version + 1}</b> and stay hidden until you press “Publish changes”.</span></div>;
  return (
    <>
      <div className="row" style={{ marginBottom: 16, flexWrap: "wrap" }}>
        <button className="iconbtn" onClick={() => nav({ chapter: c.id })} aria-label="Back"><Icon n="back" sm /></button>
        <div style={{ flex: 1 }}><h2 className="hi">{l.title}</h2><span style={{ color: "var(--muted)", fontSize: 14 }}>{c.book}</span></div>
        <span className={`chip ${statusOf(l).cls}`}>{statusOf(l).text}</span>
      </div>
      {lectureNotice}
      <div className="tabs">
        {([["lecture", "Lecture"], ["video", "Video"], ["publish", "Publish"]] as const).map(([k, n]) => <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => { setSelected(""); nav({ chapter: c.id, lesson: l.id, w: k }); }}>{n}</button>)}
      </div>
      {vjob && <JobBox key={vjob.id} job={vjob} onDone={() => { setVjob(null); void load(); }} />}
      {tab === "lecture" && (
        <div className="cols">
          <div>
            <div className="warn-bar"><Icon n="alert" sm /><span>Publishing a changed lecture rebuilds the video. <b>Video edits you made (captions, lines, scenes) will be redone</b> — you will be asked to confirm.</span></div>
            <Lecture view={view} selected={selected} onSelect={setSelected} />
          </div>
          <aside className="card panel t-side">
            <h3><Icon n="spark" sm /> Ask the editor</h3>
            <Editor key="lecture" lesson={l.id} selected={selected} view={view} kind="lecture" refresh={(v) => void set(v)} />
            <div className="t-box">
              <b>Checks</b>
              {view.checks.length === 0 ? <p>✓ All good</p> : <ul className="t-warn">{view.checks.map((x, i) => <li key={i}>{x}</li>)}</ul>}
              {view.checks.some((x) => x.includes("not used in the lecture")) && <button className="btn sm" onClick={async () => set(await call<View>("POST", `/lesson/${l.id}/archive-unused`))}>🗄 Set aside unused pictures</button>}
              <div className="row" style={{ flexWrap: "wrap" }}>
                <button className="btn sm" disabled={reviewing} onClick={runReview}><Icon n="check" sm />{reviewing ? "Reviewing…" : "Run full review"}</button>
                <button className="btn sm" disabled={view.versions.length === 0} onClick={async () => set(await call<View>("POST", `/lesson/${l.id}/undo`))}><Icon n="undo" sm />Undo ({view.versions.length})</button>
              </div>
              {review && (review.length === 0 ? <p>✓ The reviewers found nothing.</p> : <ul className="t-warn">{review.map((x, i) => <li key={i}>{x}</li>)}</ul>)}
            </div>
          </aside>
        </div>
      )}
      {tab === "video" && (
        <div className="cols">
          <div>{view.versions !== undefined && <VideoView lesson={l.id} selected={selected} onSelect={setSelected} busy={!!vjob} />}</div>
          <aside className="card panel t-side">
            <h3><Icon n="spark" sm /> Edit the video</h3>
            <p className="sub" style={{ fontSize: 13 }}>Select a line, then say what to change: a spoken line, caption, note or scene break. Only the voice is rebuilt (about a minute).</p>
            <Editor key="video" lesson={l.id} selected={selected} view={view} kind="video" refresh={(v, j) => { if (j) setVjob(j); if (v) void set(v); }} />
          </aside>
        </div>
      )}
      {tab === "publish" && (
        <div className="cols">
          <div className="card panel">
            <h2 style={{ marginBottom: 12 }}>{p.live ? "Publish changes" : "Publish lesson"}</h2>
            <div className="check"><span className={view.checks.length === 0 ? "ok" : "warn"}><Icon n={view.checks.length === 0 ? "check" : "alert"} /></span>{view.checks.length === 0 ? "Lecture checks are clean" : `${view.checks.length} check(s) need attention (see the Lecture tab)`}</div>
            <div className="check"><span className={view.pending.length === 0 ? "ok" : "warn"}><Icon n={view.pending.length === 0 ? "check" : "alert"} /></span>{view.pending.length === 0 ? "No edits waiting for Accept" : "Accept or reject the pending edit first"}</div>
            {p.live && !p.lecture_changed && !p.video_changed ? <p className="sub">Everything is live. Edit the lecture or the video to start a draft.</p> : (
              <>
                <label className="check" style={{ marginTop: 8 }}><input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} /> I have watched this lesson and approve it for students</label>
                <div className="row" style={{ marginTop: 14, flexWrap: "wrap" }}>
                  {p.live && p.video_changed && !p.lecture_changed
                    ? <button className="btn pri" disabled={!approve || !p.draft_ready || view.pending.length > 0} onClick={publishVideoDraft}>Publish video changes (v{p.version + 1})</button>
                    : <button className="btn pri" disabled={!approve || !checksOk || pub.startsWith("Publishing")} onClick={publish}>{p.live ? `Publish v${p.version + 1} (rebuilds the video)` : "Publish lesson"}</button>}
                  <a className="btn" href={`/?lesson=${p.live ? `${view.public_id}-draft` : view.public_id}`} target="_blank" rel="noreferrer"><Icon n="play" sm />Preview {p.live ? "draft" : "video"}</a>
                  {p.live && p.video_changed && <button className="btn" onClick={discard}>Discard draft video</button>}
                </div>
              </>
            )}
            {pub && <p style={{ marginTop: 10 }}>{pub}</p>}
          </div>
          <div className="card panel">
            <h3>Versions</h3>
            {p.live ? (
              <>
                {(p.lecture_changed || p.video_changed) && <div className="step cur"><b>{p.version + 1}</b>v{p.version + 1} · draft · not live</div>}
                <div className="step done"><b><Icon n="check" sm /></b>v{p.version} · <b style={{ color: "var(--teal)" }}>live for students</b></div>
                <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}><a className="btn sm" href={`/?lesson=${view.public_id}`} target="_blank" rel="noreferrer">Open student link</a></div>
              </>
            ) : <p className="sub" style={{ margin: 0 }}>Not published yet: students cannot see this lesson. After publishing, later edits go to a hidden draft until you publish them.</p>}
          </div>
        </div>
      )}
    </>
  );
}

function PublishedTab({ chapters, open }: { chapters: ChapterInfo[]; open: (c: string, l: string) => void }) {
  const rows = chapters.flatMap((c) => c.lessons.filter((l) => l.live).map((l) => ({ c, l })));
  return rows.length === 0 ? <div className="card panel"><p className="sub" style={{ margin: 0 }}>Nothing is published yet.</p></div> : (
    <div className="card" style={{ overflow: "hidden" }}>
      <table className="tbl">
        <thead><tr><th>Lesson</th><th>Live version</th><th>Actions</th></tr></thead>
        <tbody>
          {rows.map(({ c, l }) => (
            <tr key={`${c.id}/${l.id}`}>
              <td className="c-ttl"><div className="ttl"><div className="thumb t2">🎬</div><div><b className="hi">{l.title}</b><small>{c.book}</small></div></div></td>
              <td className="c-st"><span className="tag">v{l.version}</span>{l.draft && <> <span className="chip rev" style={{ fontSize: 12, padding: "2px 9px" }}>Draft v{l.version + 1}</span></>}</td>
              <td className="c-act"><div className="row"><a className="btn out sm" href={`/?lesson=${l.public_id}`}><Icon n="play" sm />Play</a><button className="btn sm" onClick={() => open(c.id, l.id)}>Edit</button></div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TeacherDashboard() {
  return <Gate title="Sign in to open the teacher dashboard"><Dashboard /></Gate>;
}

function Dashboard() {
  const { q, go } = useNav();
  const [chapters, setChapters] = useState<ChapterInfo[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const reload = useCallback(() => {
    void call<ChapterInfo[]>("GET", "/chapters").then(setChapters).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    void call<Job[]>("GET", "/jobs").then(setJobs).catch(() => undefined);
  }, []);
  useEffect(() => { reload(); const t = setInterval(reload, 8000); return () => clearInterval(t); }, [reload]);
  const [newJob, setNewJob] = useState<Job | null>(null);

  const tab = q.tab === "published" ? "published" : "chapters";
  const chapter = chapters?.find((c) => c.id === q.chapter);
  const lesson = chapter?.lessons.find((l) => l.id === q.lesson);
  const published = chapters?.flatMap((c) => c.lessons.filter((l) => l.live)).length ?? 0;
  return (
    <>
      <div className="row between" style={{ flexWrap: "wrap", marginBottom: 18 }}>
        <div><h1>Teacher dashboard</h1><p className="sub" style={{ margin: 0 }}>Review, edit and publish lessons before students see them.</p></div>
      </div>
      <div className="tabs">
        <button className={`tab ${tab === "chapters" ? "on" : ""}`} onClick={() => go({})}>Chapters</button>
        <button className={`tab ${tab === "published" ? "on" : ""}`} onClick={() => go({ tab: "published" })}>Published videos <span className="tag" style={{ padding: "1px 8px", marginLeft: 6 }}>{published}</span></button>
      </div>
      {err && <div className="warn-bar"><Icon n="alert" sm /><span>{err}</span></div>}
      {newJob && <JobBox key={newJob.id} job={newJob} onDone={() => { setNewJob(null); reload(); }} />}
      {!chapters ? <p className="sub">Loading…</p>
        : tab === "published" ? <PublishedTab chapters={chapters} open={(c, l) => go({ chapter: c, lesson: l, w: "lecture" })} />
        : chapter && lesson ? <Workspace key={`${chapter.id}/${lesson.id}`} c={chapter} l={lesson} w={q.w ?? "lecture"} nav={go} reload={reload} />
        : chapter ? <ChapterDetail c={chapter} jobs={jobs} nav={go} onJob={(j) => { setNewJob(j); reload(); }} reload={reload} />
        : <Chapters chapters={chapters} jobs={jobs} open={(c) => go({ chapter: c })} onJob={(j) => { setNewJob(j); reload(); }} onChange={reload} />}
    </>
  );
}
