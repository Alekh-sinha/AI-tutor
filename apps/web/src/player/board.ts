import type { AnimEffect, Lesson, LessonEvent } from "../../../../packages/lesson-schema/lesson";

/** A planner-made HTML figure of a live class (not part of the recorded-lesson schema). */
export interface FigureElement { type: "figure"; id: string; html: string; caption?: string }

export type BoardElement = Extract<LessonEvent, { id: string }> | FigureElement;

export interface ActiveAnim {
  effect: AnimEffect;
  since: number; // start time, used as a React key so the effect replays
}

export interface BoardState {
  elements: BoardElement[];
  highlighted: string | null;
  anims: Record<string, ActiveAnim>;
}

/** Pure function of time, so seeking and replay are always consistent. */
export function boardAt(lesson: Lesson, t: number): BoardState {
  let elements: BoardElement[] = [];
  let highlighted: string | null = null;
  let anims: Record<string, ActiveAnim> = {};
  for (const e of lesson.events) {
    if (e.t > t) break;
    if (e.type === "clear") {
      elements = [];
      highlighted = null;
      anims = {};
    } else if (e.type === "hide") {
      elements = elements.filter((x) => x.id !== e.target);
    } else if (e.type === "anim") {
      if (t < e.t + (e.dur ?? 1.6)) anims[e.target] = { effect: e.effect, since: e.t };
    } else if (e.type === "highlight") {
      highlighted = e.target;
    } else {
      elements.push(e);
    }
  }
  return { elements, highlighted, anims };
}

export function captionAt(lesson: Lesson, t: number): string {
  return lesson.narration.find((n) => t >= n.start && t < n.end)?.text ?? "";
}

const THINK_MIN_GAP = 2.5; // a silence at least this long is a "think" pause

/** If the narration is silent for a think pause at time t, how long it lasts and how much is left. */
export function thinkingAt(lesson: Lesson, t: number): { total: number; left: number } | null {
  const n = lesson.narration;
  for (let i = 0; i + 1 < n.length; i++) {
    const gap = n[i + 1].start - n[i].end;
    if (gap >= THINK_MIN_GAP && t >= n[i].end && t < n[i + 1].start) {
      return { total: gap, left: n[i + 1].start - t };
    }
  }
  return null;
}
