# AI Teacher: plan and status (updated 2026-10-14)

Product: an AI teacher for rural / underprivileged students: a white board where the teacher speaks the student's language while
photos, notes and questions appear and clear, like a human teacher. Details and decisions: CLAUDE.md.

| Phase | What | Status |
|---|---|---|
| 0-1 | Lesson timeline schema, player (audio-synced board, seek, captions, countdown clock) | done |
| 2b | Two-agent pipeline (default): brief -> Agent 1 illustrated lecture -> reviewers + editor loop -> Agent 2 director (+ code repairs) -> voice -> `<lesson>-v2` | all 4 ch6 lessons built (v2) next to the classic ones; teacher review pending |
| 2 | Content pipeline (ADK Workflow): PDF -> parse -> plan -> script (+ script reviewer) -> photos -> voice -> assemble -> picture reviewer -> DRAFT lessons + lesson list | done for NCERT Class 6 Ch.6 (4 lessons), all DRAFT: a human must watch before publishing |
| 3 | Accounts and courses, PWA offline / low-data, home-activity submission and evaluation, teacher review + publish gate, storage | not started |
| 4 | Student chat: doubt chat (text / voice / photo in, voice + whiteboard out, visible plan + thinking) and LIVE CLASS (teacher leads, child answers or raises a hand); turn-based, caps per session. Gemini Live streaming later | built, browser-tested headless (fake mic); real phone/mic not tested |
| 5 | Live class: one agent session broadcast to a cohort, question queue (features to be discussed first) | not started |
| 6 | Teacher dashboard: chapters + PDF upload, GENERATE a lesson video as a background job, lecture editor + VIDEO editor by chat (proposals, wide-change guard, accept/reject, versions + undo), full review, publish gate | built (`/?teacher=1`), needs real auth (Phase 3) and a teacher's eyes |
| later | Deploy pipeline to Agent Runtime behind Agent Gateway with VPC; more voices, avatar, languages, analytics | not started |

Run the whole Phase 2 pipeline:
`cd services/api && uv run python -m ai_teacher_api.pipeline ../../docs/source/fecu106.pdf ../../data/ch6 --book "NCERT Class 6 Science, Ch. 6"`
(resumable; `--lessons lesson-2` for one lesson; `--force` redoes everything). Player: `cd apps/web && npm run dev`, open `/`.

Known limits of Phase 2 output: Hindi voice and photos are judged only by the two AI reviewers plus the owner's spot checks;
reviewers can miss things; quiz data is generated but not shown (the question cards in the timeline are the quizzes);
the home activity is shown at the end but cannot be submitted yet (Phase 3).

Code is organised by feature (`services/api/src/ai_teacher_api/<feature>/README.md`); logs per feature in `logs/<feature>.jsonl`; symptom -> feature map in `docs/DEBUGGING.md`; tests `cd services/api && uv run pytest -q`; end-to-end `tests/e2e/`.
