# teacher — dashboard API: chapters, generate, review, edit by chat, publish
`routes.py` (chapters list/upload PDF, generate lesson job, lecture view, edit by chat on a working copy -> proposal -> accept/reject, versions + undo, full review, publish gate), `agent.py` (the editing agent: same
editor tools as the review loop + `ask_teacher` for wide/ambiguous requests), `jobs.py` (background jobs with stage + errors). Web side: `apps/web/src/teacher/` (open `/?teacher=1`).
Logs: `logs/teacher.jsonl` (`edit`, `accept`, `reject`, `undo`, `review`, `publish-*`), `logs/content.jsonl` (`job-*`). Auth: env TEACHER_TOKEN (unset = dev mode).
Symptom -> look here: "edit did something else/nothing" -> teacher.jsonl `edit` (instruction, selection, tools, outcome); "generate stuck" -> content.jsonl `job-stage` / `job-failed`; "busy" -> only one image-using job at a time (common/workspace.py). Tests: `tests/teacher/`.
