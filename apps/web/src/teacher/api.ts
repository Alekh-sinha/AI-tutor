/** Calls to the teacher API. The token (if the server has one) is typed once and kept in this browser only. */
export const getToken = () => { try { return localStorage.getItem("teacherToken") ?? ""; } catch { return ""; } };
export const setToken = (t: string) => { try { localStorage.setItem("teacherToken", t); } catch { /* private mode */ } };

let chapter = "ch6";
export const setChapter = (c: string) => { chapter = c; };
const withChapter = (path: string) => `/api/teacher${path}${path.includes("?") ? "&" : "?"}chapter=${encodeURIComponent(chapter)}`;

const headers = () => ({ "content-type": "application/json", "x-teacher-token": getToken() });

export async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(withChapter(path), { method, headers: headers(), body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) throw new Error("401");
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function stream(path: string, body: unknown, onEvent: (e: Record<string, any>) => void): Promise<void> {
  const r = await fetch(withChapter(path), { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (r.status === 401) throw new Error("401");
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 2);
      if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

export interface View {
  lesson: string; markdown: string; base_url: string; pictures: { name: string; description: string }[];
  checks: string[]; versions: number[]; pending: string[]; published: boolean; public_id: string;
  publish: { live: boolean; version: number; lecture_changed: boolean; video_changed: boolean; draft_ready: boolean };
}
export interface Proposal {
  id: string; reply: string; diff: { before: string; after: string }[]; changed_pictures: string[]; wide: boolean; base_url: string; checks: string[];
}

export interface ChapterInfo { id: string; book: string; lessons: { id: string; title: string; has_lecture: boolean; has_video: boolean; public_id: string; pending: number; live: boolean; version: number; draft: boolean; lecture_changed: boolean; video_changed: boolean }[] }
export interface Job { id: string; status: "running" | "done" | "failed"; stage: string; elapsed: number; error: string; label: string; result: Record<string, unknown> | null }

export async function uploadChapter(chapterId: string, book: string, pdf: File): Promise<Job> {
  const f = new FormData();
  f.append("chapter", chapterId); f.append("book", book); f.append("pdf", pdf);
  const r = await fetch("/api/teacher/chapters", { method: "POST", headers: { "x-teacher-token": getToken() }, body: f });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}
export interface JobLike { id: string }

/** The server's error as plain text: FastAPI sends {"detail": "..."} (or a list for invalid input). */
async function errorText(r: Response): Promise<string> {
  const j = await r.json().catch(() => null);
  const d = j?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg ?? JSON.stringify(x)).join("; ");
  return r.statusText || `HTTP ${r.status}`;
}
