import { useState } from "react";
import { RequestBox } from "./Gate";
import { useMe } from "./auth";

const CONTACT = "alekh.sinha09@gmail.com";

/** Shown at the top of every page to a signed-in user who cannot use the paid parts yet (waiting for approval, or no credit left): what they can still do, that the request has been sent, and whom to write to if it takes long. */
export function AccessNotice() {
  const { me, config } = useMe();
  if (!me?.signed_in || me.unlimited || me.role === "admin") return null;
  const contact = me.contact_email ?? config?.contact_email ?? CONTACT;
  const mail = <a href={`mailto:${contact}`}>{contact}</a>;
  if (me.status === "blocked") return <div className="warn-bar"><span><b>This account is paused.</b> You can still watch the free videos. Please write to {mail}.</span></div>;
  const pending = me.status !== "active";
  const noCredit = me.status === "active" && (me.balance_usd ?? 0) <= 0;
  if (!pending && !noCredit) return null;
  const text = (
    <>
      <b>You do not have credit to use live classes and lesson creation yet, but you can still watch the free videos.</b>
      <div>{pending ? "Your request has been sent to the admin." : "Your credit is used up."} If the approval is delayed, please write to {mail}.</div>
    </>
  );
  return (
    <>
      <Popup key={me.email} id={`${me.email}:${me.status}`}>{text}</Popup>
      <div className="warn-bar access-notice">
      <div>
        {text}
        {noCredit && <div style={{ marginTop: 8 }}><RequestBox kind="credit" /></div>}
      </div>
      </div>
    </>
  );
}

/** A popup the user must click “OK” on, so the message is not overlooked; shown once per browser session (and again after the status changes). */
function Popup({ id, children }: { id: string; children: React.ReactNode }) {
  const key = `access-popup:${id}`;
  const seen = () => { try { return sessionStorage.getItem(key) === "1"; } catch { return false; } };
  const [open, setOpen] = useState(!seen());
  if (!open) return null;
  const ok = () => { try { sessionStorage.setItem(key, "1"); } catch { /* ignore */ } setOpen(false); };
  return (
    <div className="modal-back" role="dialog" aria-modal="true">
      <div className="modal-box">
        {children}
        <button className="btn pri" autoFocus onClick={ok}>OK</button>
      </div>
    </div>
  );
}
