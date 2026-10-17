import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

export interface Me {
  signed_in: boolean;
  email?: string; name?: string; picture?: string; role?: "admin" | "user"; status?: "pending" | "active" | "blocked";
  balance_usd?: number; spent_usd?: number; today_usd?: number; daily_cap_usd?: number; unlimited?: boolean;
  open_requests?: { id: string; type: string; created: number }[];
  recent_decisions?: { type: string; status: string; usd: number; decided: number }[];
  review_note?: string; review_note_hi?: string;
}
export interface AuthConfig { auth_mode: string; google_client_id: string; dev_login: boolean; review_note: string; review_note_hi: string }

interface Ctx { me: Me | null; config: AuthConfig | null; reload: () => Promise<void> }
const MeContext = createContext<Ctx>({ me: null, config: null, reload: async () => undefined });
export const useMe = () => useContext(MeContext);

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const reload = useCallback(async () => {
    setMe(await api<Me>("/me").catch(() => ({ signed_in: false })));
  }, []);
  useEffect(() => {
    void api<AuthConfig>("/auth/config").then(setConfig).catch(() => undefined);
    void reload();
  }, [reload]);
  return <MeContext.Provider value={{ me, config, reload }}>{children}</MeContext.Provider>;
}

declare global {
  interface Window { google?: { accounts: { id: { initialize: (o: unknown) => void; renderButton: (el: HTMLElement, o: unknown) => void } } } }
}

/** Google's sign-in button. In development (AUTH_DEV_LOGIN=1 on the server) an email box is offered instead / as well. */
export function SignIn({ compact = false }: { compact?: boolean }) {
  const { config, reload } = useMe();
  const box = useRef<HTMLDivElement>(null);
  const [dev, setDev] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!config?.google_client_id || !box.current) return;
    const init = () => {
      window.google?.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async (resp: { credential: string }) => {
          try { await api("/auth/google", { body: { credential: resp.credential } }); await reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Sign-in failed"); }
        },
      });
      if (box.current) window.google?.accounts.id.renderButton(box.current, { theme: "outline", size: "large", shape: "pill", text: "signin_with", width: compact ? 200 : 260 });
    };
    if (window.google) { init(); return; }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.onload = init;
    document.head.appendChild(s);
  }, [config, reload, compact]);
  return (
    <div className="signin">
      {config?.google_client_id && <div ref={box} />}
      {config?.dev_login && (
        <div className="askbox" style={{ marginTop: 10 }}>
          <input placeholder="dev: email" value={dev} onChange={(e) => setDev(e.target.value)} />
          <button className="btn sm" onClick={async () => { await fetch(`/api/auth/dev?email=${encodeURIComponent(dev)}`); await reload(); }}>Dev sign-in</button>
        </div>
      )}
      {config && !config.google_client_id && !config.dev_login && <p className="sub">Sign-in is not configured yet.</p>}
      {err && <p className="t-warn">{err}</p>}
    </div>
  );
}
