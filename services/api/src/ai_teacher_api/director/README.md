# director — Agent 2: lecture -> video script (board cues) -> voice -> playable lesson
`agent.py` (the director's instruction; output = LessonScript + home activity), `repair.py` (CODE repairs after every round: restore dropped narration, split long lines, question-card structure,
scene per picture group, question scene with a recalled picture, board-gap notes), `script.py` (cue schema + all structural checks: rhythm, interaction, pagination = nothing scrolls),
`run_direct.py` (loop: director -> repair -> checks + storyboard reviewer -> best of 3 rounds -> TTS -> `assemble.py` -> `apps/web/public/lessons/<id>.json`), `explain.py` (interview the director).
Logs: `logs/director.jsonl` (events `round` with problems before/after repair, `repair` with counts and the restored sentences, `reviewer`, `explanation`).
Symptom -> look here: "board blank/boring stretch", "question card broken", "too few scenes", "narration differs from the lecture" -> the `round` events, then `repair.py` / `script.py` checks. Output files: `data/<chapter>/directed-<id>.json`, `direct-<id>.json` (what is left for the teacher).
Tests: `tests/director/`.
