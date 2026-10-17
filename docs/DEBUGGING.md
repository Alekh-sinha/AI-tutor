# Where to look when something is wrong
Each feature has its own folder under `services/api/src/ai_teacher_api/` (see the README in it), its own tests under `services/api/tests/<feature>/` and its own log `logs/<feature>.jsonl`
(one JSON object per line; also `GET /debug/logs/<feature>?n=100&level=error`). Tell Claude "the problem is in <feature>" and it starts from that folder + log.

| Symptom | Feature | First evidence |
|---|---|---|
| Wrong, ugly or missing picture; lecture too long; reviewer flags something odd | authoring | `data/<chapter>/illustrated/<lesson>-final/audit-*.json`, `image-attempts.jsonl`, `improve.json` |
| Board blank/boring, question card broken, too few scenes, narration differs from lecture, video too long | director | `logs/director.jsonl` (`round`, `repair`), `data/<chapter>/directed-<id>.json`, `direct-<id>.json` |
| Streaming live class: no voice, teacher can't hear a child, floor/hand problems, stuck | live | `logs/live.jsonl` (`connected`, `floor`, `teacher-turn`, `session-error`) |
| Chat or turn-based live class: no answer, no voice, rambling, wrong facts | tutor | `logs/tutor.jsonl` (`turn`, `say`, `tts-failed`) |
| Dashboard: edit wrong, accept/undo, publish blocked, generate stuck, upload fails | teacher (+ content for jobs) | `logs/teacher.jsonl`, `logs/content.jsonl` (`job-failed` has a trace) |
| PDF parse / lesson plan wrong; pipeline stops | content | `logs/content.jsonl`, `data/<chapter>/plan.json` |
| Player UI (seek, captions, layout) | `apps/web/src/player` | browser console; `tests/e2e/ui_smoke.py` |

Ask an agent WHY it did something: `uv run python -m ai_teacher_api.director.explain ../../data/ch6 lesson-3 "why so few scenes?"` and `...authoring.explain ... "why only 7 pictures?"` (answers are logged as `explanation`).
Tests: `cd services/api && uv run pytest -q` (no network, ~3 s). End to end (servers running): `uv run python ../../tests/e2e/api_smoke.py` and
`cd <any non-project dir> && uv run --offline --with playwright==1.63.0 python -u <repo>/tests/e2e/ui_smoke.py <screenshot-dir>`.
