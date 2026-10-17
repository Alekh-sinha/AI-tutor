import { useEffect, useState, type ReactNode } from "react";
import { api, usd, watchAccessErrors } from "./api";
import { RequestBox } from "./Gate";
import { Icon } from "./icons";
import { SignIn, useMe } from "./auth";

export type NavKey = "home" | "lessons" | "live" | "teacher" | "admin" | "";
const NAV: { key: NavKey; href: string; label: string; icon: string; admin?: boolean }[] = [
  { key: "home", href: "/", label: "Home", icon: "home" },
  { key: "lessons", href: "/lessons", label: "Lessons", icon: "file" },
  { key: "live", href: "/live", label: "Live Classes", icon: "video" },
  { key: "teacher", href: "/teacher", label: "Teacher dashboard", icon: "layout" },
  { key: "admin", href: "/admin", label: "Admin", icon: "shield", admin: true },
];

interface AccessEvent { code: string; message: string; hi: string }

export function AccessDialog() {
  const [ev, setEv] = useState<AccessEvent | null>(null);
  useEffect(() => {
    const on = (e: Event) => setEv((e as CustomEvent<AccessEvent>).detail);
    window.addEventListener("ss-access", on);
    return () => window.removeEventListener("ss-access", on);
  }, []);
  if (!ev) return null;
  const titles: Record<string, string> = { credit_exhausted: "Your credit is used up", daily_cap: "Today's limit is reached", not_approved: "Waiting for approval", blocked: "Account paused", sign_in: "Please sign in", unsafe: "We can't help with that" };
  return (
    <div className="modal" role="dialog" onClick={() => setEv(null)}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>{titles[ev.code] ?? "Notice"}</h2>
        <p>{ev.message}</p>
        {ev.hi && <p className="hi sub">{ev.hi}</p>}
        {ev.code === "credit_exhausted" && <RequestBox kind="credit" />}
        {ev.code === "not_approved" && <RequestBox kind="access" />}
        {ev.code === "sign_in" && <SignIn />}
        <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}><button className="btn" onClick={() => setEv(null)}>Close</button></div>
      </div>
    </div>
  );
}

/** App frame from the approved design: sidebar on desktop, bottom tabs on a phone, a top bar with the credit balance and the account menu. */
export function Shell({ active, children }: { active: NavKey; children: ReactNode }) {
  const { me } = useMe();
  const [menu, setMenu] = useState(false);
  const [open, setOpen] = useState(0);
  useEffect(() => watchAccessErrors(), []);
  useEffect(() => {
    if (me?.role === "admin") void api<{ open_access_requests: number; open_credit_requests: number }>("/admin/overview").then((o) => setOpen(o.open_access_requests + o.open_credit_requests)).catch(() => undefined);
  }, [me?.role]);
  const items = NAV.filter((n) => !n.admin || me?.role === "admin");
  const initial = (me?.name || me?.email || "?").slice(0, 1).toUpperCase();
  const decision = me?.recent_decisions?.[0];
  const seen = (() => { try { return localStorage.getItem("seenDecision"); } catch { return null; } })();
  const showDecision = !!decision && String(decision.decided) !== seen && Date.now() / 1000 - decision.decided < 3 * 86400;
  return (
    <div className="ss app">
      <aside className="side">
        <a className="logo" href="/"><span className="mark hi">सा</span><span>Seekho <b>Saathi</b></span></a>
        <nav className="nav">
          {items.map((n) => <a key={n.key} href={n.href} className={n.key === active ? "on" : ""}><Icon n={n.icon} /><span>{n.label}</span>{n.key === "admin" && open > 0 && <em className="navbadge">{open}</em>}</a>)}
        </nav>
        <div className="foot">Lessons and classes are taught in <b>Hindi</b>.<br />This screen is in English.</div>
      </aside>
      <div className="main">
        <header className="top">
          <a className="mlogo" href="/"><span className="mark hi">सा</span>Seekho Saathi</a>
          <div className="row">
            {me?.signed_in && me.status === "active" && !me.unlimited && <span className={`credit ${(me.balance_usd ?? 0) <= 1 ? "low" : ""}`} title="Your remaining credit"><Icon n="coin" sm /> {usd(me.balance_usd ?? 0)} left</span>}
            {me?.role === "admin" && <a className="bell" href="/admin" aria-label="Requests"><Icon n="bell" />{open > 0 && <i />}</a>}
            {me?.signed_in ? (
              <div className="me" onClick={() => setMenu(!menu)} style={{ cursor: "pointer", position: "relative" }}>
                {me.picture ? <img className="av" src={me.picture} alt="" referrerPolicy="no-referrer" /> : <div className="av">{initial}</div>}
                <span>{(me.name || me.email || "").split(" ")[0]}</span><Icon n="chev" sm />
                {menu && (
                  <div className="menu" onClick={(e) => e.stopPropagation()}>
                    <p className="sub" style={{ margin: "0 0 8px", fontSize: 13 }}>{me.email}<br />{me.unlimited ? "Admin" : me.status === "active" ? `${usd(me.today_usd ?? 0)} used today (limit ${usd(me.daily_cap_usd ?? 0)})` : "Waiting for approval"}</p>
                    {me.status === "active" && !me.unlimited && <button className="btn sm" onClick={() => { setMenu(false); window.dispatchEvent(new CustomEvent("ss-access", { detail: { code: "credit_exhausted", message: "Ask the admin for more credit. Requests are reviewed every day after 9:00 PM IST.", hi: "" } })); }}>Request more credit</button>}
                    <button className="btn sm" onClick={async () => { await api("/auth/logout", { method: "POST" }); location.href = "/"; }}><Icon n="logout" sm /> Sign out</button>
                  </div>
                )}
              </div>
            ) : me ? <SignIn compact /> : null}
          </div>
        </header>
        {showDecision && decision && (
          <div className="page" style={{ paddingBottom: 0 }}>
            <div className={decision.status === "approved" ? "note-bar" : "warn-bar"}>
              <span>{decision.type === "access" ? "Access request" : "Credit request"}: {decision.status === "approved" ? `approved${decision.usd ? ` — ${usd(decision.usd)} added` : ""}.` : "not approved this time. You can send another request."}</span>
              <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => { try { localStorage.setItem("seenDecision", String(decision.decided)); } catch { /* private mode */ } location.reload(); }}>OK</button>
            </div>
          </div>
        )}
        <main className="page">{children}</main>
      </div>
      <nav className="mtab">
        {items.map((n) => <a key={n.key} href={n.href} className={n.key === active ? "on" : ""}><Icon n={n.icon} />{n.label.replace("Teacher dashboard", "Teacher").replace("Live Classes", "Live")}</a>)}
      </nav>
      <AccessDialog />
    </div>
  );
}
