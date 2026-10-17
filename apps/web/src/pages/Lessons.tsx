import { useEffect, useState } from "react";
import { Icon } from "../ss/icons";

export interface IndexEntry { id: string; title: string; duration: number; status: string; public?: boolean }
const TILES = ["🏺", "🪟", "🧺", "🧂", "💡", "🧲", "🌱", "🔬"];
const TINTS = ["t1", "t2", "t3", "t4"];

export const splitTitle = (t: string) => {
  const [name, ...tags] = t.split(" · ");
  return { name, tag: tags.join(" · ") };
};

export function useLessons() {
  const [items, setItems] = useState<IndexEntry[] | null>(null);
  useEffect(() => {
    fetch("/lessons/index.json").then((r) => (r.ok ? r.json() : [])).then(setItems).catch(() => setItems([]));
  }, []);
  return items;
}

export function LessonsTable({ items }: { items: IndexEntry[] }) {
  if (items.length === 0) return <div className="card panel"><p className="sub" style={{ margin: 0 }}>No lessons to show yet.</p></div>;
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <table className="tbl">
        <thead><tr><th>Title</th><th>Type</th><th>Status</th><th>Length</th><th>Actions</th></tr></thead>
        <tbody>
          {items.map((l, i) => {
            const { name, tag } = splitTitle(l.title);
            const chip = l.public ? ["ready", "Free for everyone"] : l.status === "published" ? ["ready", "Published"] : ["rev", "Draft"];
            return (
              <tr key={l.id}>
                <td className="c-ttl"><div className="ttl"><div className={`thumb ${TINTS[i % 4]}`}>{TILES[i % TILES.length]}</div><div><b className="hi">{name}</b><small>{tag || "Hindi video lesson"}</small></div></div></td>
                <td className="c-type"><span className="tag"><Icon n="video" sm />Video · Hindi</span></td>
                <td className="c-st"><span className={`chip ${chip[0]}`}>{chip[1]}</span></td>
                <td className="c-date" style={{ color: "var(--muted)" }}>{Math.max(1, Math.round(l.duration / 60))} min</td>
                <td className="c-act"><div className="row"><a className="btn out sm" href={`/?lesson=${l.id}`}><Icon n="play" sm />Play</a><a className="btn sm" href={`/?room=new&lesson=${l.id}`}>Live class</a></div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Lessons() {
  const items = useLessons();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "free" | "mine">("all");
  const shown = (items ?? []).filter((l) => (filter === "all" || (filter === "free" ? l.public : !l.public)) && l.title.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="row between" style={{ flexWrap: "wrap", marginBottom: 18 }}>
        <div><h1>Lessons</h1><p className="sub" style={{ margin: 0 }}>Video lessons you can watch. Free lessons need no account.</p></div>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <label className="search"><Icon n="search" sm /><input placeholder="Search lessons" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <a className="btn pri" href="/teacher"><Icon n="upload" sm />New lesson</a>
        </div>
      </div>
      <div className="seg" style={{ marginBottom: 16 }}>
        {([["all", "All"], ["free", "Free"], ["mine", "My lessons"]] as const).map(([k, n]) => <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{n}</button>)}
      </div>
      {items ? <LessonsTable items={shown} /> : <p className="sub">Loading…</p>}
    </>
  );
}
