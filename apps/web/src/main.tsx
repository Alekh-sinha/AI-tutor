import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Report JavaScript errors to the API log (logs/app.jsonl) so a broken screen leaves evidence.
const report = (kind: string, message: string, stack = "") => {
  try {
    navigator.sendBeacon("/api/client-log", new Blob([JSON.stringify({ kind, message: message.slice(0, 500), stack: stack.slice(0, 1500), url: location.href.slice(0, 300) })], { type: "application/json" }));
  } catch { /* logging must never break the page */ }
};
window.addEventListener("error", (e) => report("error", e.message, e.error?.stack ?? ""));
window.addEventListener("unhandledrejection", (e) => report("rejection", String(e.reason), e.reason?.stack ?? ""));
