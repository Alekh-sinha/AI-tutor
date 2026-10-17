import { useCallback, useEffect, useRef, useState } from "react";
import type { Lesson } from "../../../../packages/lesson-schema/lesson";

/**
 * Playback clock. Uses the audio element's clock when the lesson has narration audio,
 * otherwise a timer (silent preview), so events always follow what the student hears.
 */
export function usePlayer(lesson: Lesson) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timeRef = useRef(0);

  useEffect(() => {
    audioRef.current = lesson.audio ? new Audio(lesson.audio) : null;
    return () => audioRef.current?.pause();
  }, [lesson.audio]);

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    audioRef.current?.play().catch(() => setPlaying(false));
    const tick = (now: number) => {
      const audio = audioRef.current;
      timeRef.current = audio ? audio.currentTime : timeRef.current + (now - last) / 1000;
      last = now;
      if (timeRef.current >= lesson.duration) {
        timeRef.current = lesson.duration;
        setTime(lesson.duration);
        setPlaying(false);
        return;
      }
      setTime(timeRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      audioRef.current?.pause();
    };
  }, [playing, lesson.duration]);

  const seek = useCallback((t: number) => {
    timeRef.current = t;
    setTime(t);
    if (audioRef.current) audioRef.current.currentTime = t;
  }, []);

  const toggle = useCallback(() => {
    if (timeRef.current >= lesson.duration) seek(0);
    setPlaying((p) => !p);
  }, [lesson.duration, seek]);

  return { time, playing, toggle, seek };
}
