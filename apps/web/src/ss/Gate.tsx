import { useState, type ReactNode } from "react";
import { api } from "./api";
import { SignIn, useMe } from "./auth";

/** Ask the admin for access (new users) or for more credit (used up). The admin decides once a day, after 9 PM IST: the text says so, so nobody waits anxiously. */
export function RequestBox({ kind }: { kind: "access" | "credit" }) {
  const { me, reload } = useMe();
  const [note, setNote] = useState("");
  const [sent, setSent] = useState("");
  const [err, setErr] = useState("");
  const open = me?.open_requests?.some((r) => r.type === kind);
  const send = async () => {
    try {
      const r = await api<{ status: string; message: string }>(kind === "access" ? "/access/request" : "/credit/request", { body: { note } });
      setSent(r.message); await reload();
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not send"); }
  };
  if (open || sent) {
    return (
      <div className="note-bar"><span>✔ Your request is with the admin. {me?.review_note ?? sent}</span></div>
    );
  }
  return (
    <div>
      <textarea className="note-input" rows={2} maxLength={400} placeholder={kind === "access" ? "Who are you and what will you use it for? (optional)" : "Why do you need more credit? (optional)"} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
        <button className="btn pri" onClick={send}>{kind === "access" ? "Request access" : "Request more credit"}</button>
        <span className="sub" style={{ margin: 0, fontSize: 13 }}>{me?.review_note ?? "Requests are reviewed every day after 9:00 PM IST."}</span>
      </div>
      {err && <p className="t-warn">{err}</p>}
    </div>
  );
}

/** Wraps a page that needs an approved account. Free lessons never need it. */
export function Gate({ children, title = "Sign in to continue" }: { children: ReactNode; title?: string }) {
  const { me } = useMe();
  if (!me) return <p className="sub">Loading…</p>;
  if (!me.signed_in) {
    return (
      <div className="card gate">
        <h2>{title}</h2>
        <p className="sub">Watching the free lessons needs no account. Live classes, the teacher chat and lesson creation need a signed-in, approved account.</p>
        <SignIn />
      </div>
    );
  }
  if (me.status === "blocked") {
    return <div className="card gate"><h2>This account is paused</h2><p className="sub">Please contact the admin. The free lessons stay available.</p></div>;
  }
  if (me.status !== "active") {
    return (
      <div className="card gate">
        <h2>Welcome{me.name ? `, ${me.name.split(" ")[0]}` : ""}!</h2>
        <p className="sub">Your account is created. To use live classes and lesson creation, the admin needs to approve it and give you some credit. You can still watch the free lessons in the meantime.</p>
        <RequestBox kind="access" />
        {me.recent_decisions?.[0]?.type === "access" && me.recent_decisions[0].status === "rejected" && <p className="t-warn">Your last request was not approved. You can send another one.</p>}
      </div>
    );
  }
  return <>{children}</>;
}
