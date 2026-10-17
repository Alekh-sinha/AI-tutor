import "./live/live.css";
import "./App.css";
import "./ui.css";
import { useEffect, useState, type ReactNode } from "react";
import type { Lesson } from "../../../packages/lesson-schema/lesson";
import { ChatPanel } from "./chat/ChatPanel";
import { LiveClass } from "./chat/LiveClass";
import { LiveEntry } from "./live/LiveEntry";
import { Admin } from "./pages/Admin";
import { Home } from "./pages/Home";
import { Lessons } from "./pages/Lessons";
import { LivePage } from "./pages/LivePage";
import { Player } from "./pages/Player";
import { AccessDialog, Shell, type NavKey } from "./ss/Shell";
import { watchAccessErrors } from "./ss/api";
import { Login } from "./ss/Login";
import { MeProvider, SignIn, useMe } from "./ss/auth";
import { TeacherDashboard } from "./teacher/Dashboard";

/** Full-screen experiences (live room, chat) keep their own layout but share the sign-in context and the "credit used up" dialog. */
function FullScreen({ children }: { children: ReactNode }) {
  useEffect(() => watchAccessErrors(), []);
  return <div className="ss">{children}<AccessDialog /></div>;
}

function LessonPage({ id }: { id: string }) {
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [err, setErr] = useState<{ status: number; text: string } | null>(null);
  useEffect(() => {
    fetch(`/lessons/${id}.json`).then(async (r) => {
      if (r.ok) setLesson(await r.json());
      else setErr({ status: r.status, text: (await r.json().catch(() => null))?.detail?.message ?? "This lesson could not be opened." });
    }).catch(() => setErr({ status: 0, text: "Could not reach the server." }));
  }, [id]);
  if (err) return <div className="card gate"><h2>{err.status === 401 ? "Please sign in" : "Can't open this lesson"}</h2><p className="sub">{err.text}</p>{err.status === 401 && <SignIn />}</div>;
  return lesson ? <Player lesson={lesson} /> : <p className="sub">Loading…</p>;
}

function Page({ active, children, open = false }: { active: NavKey; children: ReactNode; open?: boolean }) {
  const { me } = useMe();
  if (!open && me && !me.signed_in) return <div className="ss"><Login /></div>;  // nobody gets past here without signing in (a shared lesson link is the one exception)
  if (!open && !me) return <div className="ss"><p className="sub" style={{ padding: 24 }}>Loading…</p></div>;
  return <Shell active={active}>{children}</Shell>;
}

export default function App() {
  const params = new URLSearchParams(location.search);
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const id = params.get("lesson");
  let view: ReactNode;
  if (params.has("teacher")) { location.replace("/teacher"); view = null; }
  else if (params.has("room")) view = <FullScreen><LiveEntry lessonId={params.get("lesson") ?? ""} joinCode={params.get("room") === "new" ? "" : params.get("room") ?? ""} /></FullScreen>;
  else if (params.has("join")) view = <FullScreen><LiveEntry lessonId="join" joinCode="" /></FullScreen>;
  else if (!id && params.has("chat")) view = <FullScreen><ChatPanel onClose={() => { location.href = "/"; }} /></FullScreen>;
  else if (!id && params.has("live")) view = <FullScreen><LiveClass lessonId="" getTime={() => 0} onClose={() => { location.href = "/"; }} /></FullScreen>;
  else if (id) view = <Page active="lessons" open><LessonPage id={id} /></Page>;
  else if (path === "/lessons") view = <Page active="lessons"><Lessons /></Page>;
  else if (path === "/live") view = <Page active="live"><LivePage /></Page>;
  else if (path === "/teacher") view = <Page active="teacher"><TeacherDashboard /></Page>;
  else if (path === "/admin") view = <Page active="admin"><Admin /></Page>;
  else view = <Page active="home"><Home /></Page>;
  return <MeProvider>{view}</MeProvider>;
}
