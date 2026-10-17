import type { HomeActivity } from "../../../../packages/lesson-schema/lesson";

/** Shown when the timeline ends: the home activity, and a replay button. */
export function Ended({ activity, onReplay }: { activity?: HomeActivity | null; onReplay: () => void }) {
  return (
    <div className="quiz">
      {activity && (
        <div className="activity">
          <h3>🏠 घर का काम: {activity.title}</h3>
          <p>{activity.instructions}</p>
        </div>
      )}
      <button className="next" onClick={onReplay}>↺ फिर से देखें</button>
    </div>
  );
}
