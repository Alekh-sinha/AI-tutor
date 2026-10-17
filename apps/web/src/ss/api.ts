/** Calls to the API (same address, `/api/...`). The session cookie travels automatically. Errors carry the server's stable `code` and its English / Hindi texts. */
export class ApiError extends Error {
  status: number;
  code: string;
  hi: string;
  constructor(status: number, code: string, message: string, hi = "") {
    super(message);
    this.status = status;
    this.code = code;
    this.hi = hi;
  }
}

export async function readError(r: Response): Promise<ApiError> {
  const j = await r.clone().json().catch(() => null);
  const d = j?.detail;
  if (d && typeof d === "object" && !Array.isArray(d)) return new ApiError(r.status, d.code ?? "error", d.message ?? r.statusText, d.message_hi ?? "");
  if (typeof d === "string") return new ApiError(r.status, "error", d);
  if (Array.isArray(d)) return new ApiError(r.status, "invalid", d.map((x) => x.msg ?? JSON.stringify(x)).join("; "));
  return new ApiError(r.status, "error", r.statusText || `HTTP ${r.status}`);
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: init.method ?? (init.body !== undefined ? "POST" : "GET"),
    headers: init.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (!r.ok) throw await readError(r);
  return r.json() as Promise<T>;
}

/** Codes that mean "you cannot use the AI right now": the shell shows them in one place (a dialog with the next step), whichever request hit them. */
export const ACCESS_CODES = new Set(["not_approved", "blocked", "credit_exhausted", "daily_cap", "sign_in", "unsafe"]);

export function watchAccessErrors(): void {
  const w = window as unknown as { __ssFetch?: boolean };
  if (w.__ssFetch) return;
  w.__ssFetch = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (...a: Parameters<typeof fetch>) => {
    const r = await orig(...a);
    const url = typeof a[0] === "string" ? a[0] : a[0] instanceof Request ? a[0].url : String(a[0]);
    if (!r.ok && [401, 402, 403, 422, 429].includes(r.status) && url.includes("/api/") && !url.includes("/api/me") && !url.includes("/api/auth/")) {
      const e = await readError(r);
      if (ACCESS_CODES.has(e.code)) window.dispatchEvent(new CustomEvent("ss-access", { detail: { code: e.code, message: e.message, hi: e.hi } }));
    }
    return r;
  };
}

export const usd = (n: number) => `$${n.toFixed(2)}`;
export const when = (ts?: number | null) => (ts ? new Date(ts * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "—");
