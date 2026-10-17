// Mirrors services/api/src/ai_teacher_api/lesson.py (source of truth).
/** Words drawn by the player over an image; x/y are % of the image box, size is % of its width. */
export interface Label {
  text: string;
  x: number;
  y: number;
  size?: number;
  color?: string | null;
  bold?: boolean;
}

export type NoteStyle = "heading" | "body" | "bullet" | "key";

export type LessonEvent =
  | { type: "note"; t: number; id: string; text: string; style?: NoteStyle }
  | { type: "image"; t: number; id: string; src: string; caption?: string | null }
  | { type: "svg"; t: number; id: string; markup: string; labels?: Label[]; caption?: string | null }
  | { type: "equation"; t: number; id: string; latex: string }
  | { type: "highlight"; t: number; target: string }
  | { type: "clear"; t: number }
  | { type: "hide"; t: number; target: string }
  | { type: "choice"; t: number; id: string; question: string; options: string[]; answer_index: number; reveal_at: number }
  | { type: "anim"; t: number; target: string; effect: AnimEffect; dur?: number };

export type AnimEffect = "pulse" | "shake" | "bounce" | "tick" | "cross" | "arrow" | "glow";

export interface QuizQuestion {
  question: string;
  options: string[];
  answer_index: number;
  explanation: string;
}

export interface HomeActivity {
  title: string;
  instructions: string;
  submit_as: string;
  rubric: string[];
  source_activity?: string | null;
}

export interface NarrationLine {
  start: number;
  end: number;
  text: string;
}

export interface Source {
  book: string;
  page?: number | null;
  section?: string | null;
}

export interface Lesson {
  id: string;
  title: string;
  language: string;
  duration: number;
  audio?: string | null;
  narration: NarrationLine[];
  events: LessonEvent[];
  sources?: Source[];
  quiz?: QuizQuestion[];
  activity?: HomeActivity | null;
}
