import { useCallback, useEffect, useState } from "react";
import { api, usd, when } from "../ss/api";
import { Gate } from "../ss/Gate";
import { Icon } from "../ss/icons";
import { useMe } from "../ss/auth";

interface User { email: string; name: string; role: string; status: string; balance_usd: number; credit_usd: number; spent_usd: number; today_usd: number; daily_cap_usd: number; last_login: number; login_count: number; counters: Record<string, number> }
interface Overview { users: number; active: number; pending_users: number; open_access_requests: number; open_credit_requests: number; spent_today_usd: number; spent_total_usd: number; granted_total_usd: number; logged_in_today: number; flags: number }
interface Req { id: string; email: string; type: string; note: string; created: number }
interface Flag { id: string; ts: number; email: string; where: string; decision: string; reason: string; text: string }
interface Detail { user: User; ledger: { ts: number; kind: string; model: string; usd: number; detail: string }[] }
interface LessonRow { id: string; title: string; status: string }

const chipFor = (s: string) => (s === "active" ? "ready" : s === "blocked" ? "draft" : "gen");

function RequestRow({ r, done }: { r: Req; done: () => void }) {
  const [amount, setAmount] = useState(10);
  const decide = async (approve: boolean) => { await api(`/admin/requests/${r.id}/decide`, { body: { approve, usd: amount } }); done(); };
  return (
    <tr>
      <td className="c-ttl"><div className="ttl"><div className="thumb t2" style={{ fontSize: 18 }}>{r.type === "access" ? "🙋" : "💳"}</div><div><b>{r.email}</b><small>{r.note || "No note"} · {when(r.created)}</small></div></div></td>
      <td className="c-type"><span className={`chip ${r.type === "access" ? "gen" : "rev"}`}>{r.type === "access" ? "Access request" : "More credit"}</span></td>
      <td className="c-act">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <label className="row" style={{ gap: 4 }}>$<input className="t-input" style={{ width: 70 }} type="number" min={0} step={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} /></label>
          <button className="btn grn sm" onClick={() => decide(true)}><Icon n="check" sm />Approve</button>
          <button className="btn sm" onClick={() => decide(false)}><Icon n="x" sm />Reject</button>
        </div>
      </td>
    </tr>
  );
}

function UserPanel({ email, close, changed }: { email: string; close: () => void; changed: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [usdIn, setUsdIn] = useState(10);
  const [cap, setCap] = useState(0);
  const load = useCallback(async () => { const x = await api<Detail>(`/admin/users/${encodeURIComponent(email)}`); setD(x); setCap(x.user.daily_cap_usd); }, [email]);
  useEffect(() => { void load(); }, [load]);
  if (!d) return null;
  const u = d.user;
  const act = async (p: string, body: unknown) => { await api(`/admin/users/${encodeURIComponent(email)}/${p}`, { body }); await load(); changed(); };
  return (
    <div className="card panel" style={{ marginTop: 16 }}>
      <div className="row between"><h3 style={{ margin: 0 }}>{u.name || u.email} <span className={`chip ${chipFor(u.status)}`}>{u.status}</span></h3><button className="iconbtn" onClick={close} aria-label="Close"><Icon n="x" sm /></button></div>
      <p className="sub" style={{ margin: "6px 0 12px" }}>{u.email} · {u.login_count} logins · last seen {when(u.last_login)}</p>
      <div className="stat stat4"><div className="card"><b>{usd(u.balance_usd)}</b><span>Balance</span></div><div className="card"><b>{usd(u.spent_usd)}</b><span>Spent in total</span></div><div className="card"><b>{usd(u.today_usd)}</b><span>Spent today (cap {usd(u.daily_cap_usd)})</span></div><div className="card"><b>{Math.round((u.counters?.live_seconds ?? 0) / 60)} min</b><span>Live class time</span></div></div>
      <div className="row" style={{ flexWrap: "wrap", marginBottom: 14 }}>
        <label className="row" style={{ gap: 4 }}>$<input className="t-input" style={{ width: 80 }} type="number" value={usdIn} onChange={(e) => setUsdIn(Number(e.target.value))} /></label>
        <button className="btn pri sm" disabled={usdIn <= 0} onClick={() => act("grant", { usd: usdIn })}>Add credit</button>
        <label className="row" style={{ gap: 4, marginLeft: 10 }}>Daily cap $<input className="t-input" style={{ width: 70 }} type="number" value={cap} onChange={(e) => setCap(Number(e.target.value))} /></label>
        <button className="btn sm" onClick={() => act("cap", { usd: cap })}>Set cap</button>
        {u.role !== "admin" && (u.status === "blocked"
          ? <button className="btn sm" onClick={() => act("status", { status: "active" })}>Unblock</button>
          : <button className="btn sm" style={{ color: "var(--red)" }} onClick={() => act("status", { status: "blocked" })}>Block</button>)}
      </div>
      <b>Recent usage</b>
      <table className="tbl" style={{ marginTop: 8 }}>
        <thead><tr><th>When</th><th>What</th><th>Model</th><th>Amount</th></tr></thead>
        <tbody>{d.ledger.length === 0 ? <tr><td colSpan={4} style={{ color: "var(--muted)" }}>No usage yet.</td></tr> : d.ledger.map((r, i) => <tr key={i}><td>{when(r.ts)}</td><td>{r.kind}{r.detail ? ` · ${r.detail}` : ""}</td><td>{r.model}</td><td>{r.usd < 0 ? `+${usd(-r.usd)} credit` : usd(r.usd)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function AdminPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [reqs, setReqs] = useState<Req[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [lessons, setLessons] = useState<{ lessons: LessonRow[]; public: string[] } | null>(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState("");
  const load = useCallback(() => {
    void api<Overview>("/admin/overview").then(setOv);
    void api<Req[]>("/admin/requests").then(setReqs);
    void api<User[]>("/admin/users").then(setUsers);
    void api<Flag[]>("/admin/flags").then(setFlags);
    void api<{ lessons: LessonRow[]; public: string[] }>("/admin/lessons").then(setLessons);
  }, []);
  useEffect(() => { load(); }, [load]);
  const togglePublic = async (id: string) => {
    if (!lessons) return;
    const next = lessons.public.includes(id) ? lessons.public.filter((x) => x !== id) : [...lessons.public, id];
    await api("/admin/public-lessons", { body: { ids: next } });
    load();
  };
  const shown = users.filter((u) => `${u.email} ${u.name}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <h1>Admin</h1>
      <p className="sub">Who signed in, who has credit, and what needs your decision. Requests are decided once a day after 9:00 PM IST.</p>
      {ov && (
        <div className="stat" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
          <div className="card"><b>{ov.users}</b><span>Users ({ov.logged_in_today} signed in today)</span></div>
          <div className="card"><b>{ov.active}</b><span>Approved</span></div>
          <div className="card"><b>{ov.open_access_requests + ov.open_credit_requests}</b><span>Waiting for you</span></div>
          <div className="card"><b>{usd(ov.spent_today_usd)}</b><span>Spent today</span></div>
          <div className="card"><b>{usd(ov.spent_total_usd)}</b><span>Spent in total (of {usd(ov.granted_total_usd)} granted)</span></div>
          <div className="card"><b>{ov.flags}</b><span>Safety flags</span></div>
        </div>
      )}
      <h2 style={{ margin: "8px 0 12px" }}>Requests</h2>
      {reqs.length === 0 ? <div className="card panel"><p className="sub" style={{ margin: 0 }}>Nothing is waiting. ✔</p></div> : (
        <div className="card" style={{ overflow: "hidden" }}><table className="tbl"><thead><tr><th>Who</th><th>Type</th><th>Decision</th></tr></thead><tbody>{reqs.map((r) => <RequestRow key={r.id} r={r} done={load} />)}</tbody></table></div>
      )}
      <div className="row between" style={{ margin: "26px 0 12px", flexWrap: "wrap" }}>
        <h2>Users</h2>
        <label className="search"><Icon n="search" sm /><input placeholder="Search users" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>
      <div className="card" style={{ overflow: "hidden" }}>
        <table className="tbl">
          <thead><tr><th>User</th><th>Status</th><th>Balance</th><th>Spent</th><th>Last seen</th><th /></tr></thead>
          <tbody>
            {shown.map((u) => (
              <tr key={u.email} onClick={() => setSel(u.email)} style={{ cursor: "pointer" }}>
                <td className="c-ttl"><div className="ttl"><div className="thumb t3" style={{ fontSize: 18 }}>{(u.name || u.email)[0].toUpperCase()}</div><div><b>{u.name || u.email}</b><small>{u.email}{u.role === "admin" ? " · admin" : ""}</small></div></div></td>
                <td className="c-st"><span className={`chip ${chipFor(u.status)}`}>{u.status}</span></td>
                <td className="c-type">{u.role === "admin" ? "∞" : usd(u.balance_usd)}</td>
                <td className="c-date">{usd(u.spent_usd)} <small style={{ color: "var(--muted)" }}>({usd(u.today_usd)} today)</small></td>
                <td className="c-date" style={{ color: "var(--muted)" }}>{when(u.last_login)} · {u.login_count}×</td>
                <td className="c-act"><button className="btn sm">Open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sel && <UserPanel email={sel} close={() => setSel("")} changed={load} />}
      <h2 style={{ margin: "26px 0 12px" }}>Free lessons</h2>
      <div className="card panel">
        <p className="sub" style={{ marginTop: 0 }}>Anyone can watch these without signing in, and they cost nothing even when credit is gone.</p>
        {lessons?.lessons.filter((l) => !l.id.endsWith("-draft")).map((l) => (
          <label key={l.id} className="check"><input type="checkbox" checked={lessons.public.includes(l.id)} onChange={() => togglePublic(l.id)} /> <span className="hi">{l.title}</span> <small style={{ color: "var(--muted)" }}>{l.id}</small></label>
        ))}
      </div>
      <h2 style={{ margin: "26px 0 12px" }}>Safety flags</h2>
      {flags.length === 0 ? <div className="card panel"><p className="sub" style={{ margin: 0 }}>No messages were flagged.</p></div> : (
        <div className="card" style={{ overflow: "hidden" }}><table className="tbl"><thead><tr><th>When</th><th>Who</th><th>Where</th><th>Decision</th><th>Message</th></tr></thead><tbody>
          {flags.map((f) => <tr key={f.id}><td>{when(f.ts)}</td><td>{f.email || "—"}</td><td>{f.where}</td><td><span className={`chip ${f.decision === "distress" ? "gen" : "draft"}`}>{f.decision}</span> <small>{f.reason}</small></td><td className="hi">{f.text}</td></tr>)}
        </tbody></table></div>
      )}
    </>
  );
}

export function Admin() {
  const { me } = useMe();
  return (
    <Gate title="Sign in as the admin">
      {me?.role === "admin" ? <AdminPage /> : <div className="card gate"><h2>Admin only</h2><p className="sub">This page is for the site admin.</p></div>}
    </Gate>
  );
}
