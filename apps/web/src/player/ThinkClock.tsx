/** Ticking countdown shown while the teacher waits for the student to think. */
export function ThinkClock({ total, left }: { total: number; left: number }) {
  const R = 22;
  const C = 2 * Math.PI * R;
  return (
    <div className="think" role="timer" aria-label="सोचिए">
      <svg viewBox="0 0 52 52" width="64" height="64">
        <circle cx="26" cy="26" r={R} className="think-track" />
        <circle
          cx="26"
          cy="26"
          r={R}
          className="think-arc"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - left / total)}
          transform="rotate(-90 26 26)"
        />
        <text x="26" y="26" className="think-num">{Math.ceil(left)}</text>
      </svg>
      <span className="think-label">सोचिए 🤔</span>
    </div>
  );
}
