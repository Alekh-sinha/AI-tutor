# content — book PDF -> chapter -> plan -> lessons
`chapter.py` (liteparse), `plan.py` + `run_plan.py` + `planner.py` (+ `skills/lesson-planning`), `brief.py` ("what the book says" per lesson, the authority for Agent 1, the tutor and the reviewers),
`run_lesson.py` (ONE lesson end to end: brief -> Agent 1 -> review/edit loop -> Agent 2 -> voice; resumable stages), `pipeline.py` (whole chapter as an ADK Workflow; `--approach agents|classic`).
Logs: `logs/content.jsonl` (events `draft`, `improve`, `lesson-built`, `job-*`). Tests: `tests/content/`.
Symptom -> look here: "lesson generation fails / stuck" -> content.jsonl `job-failed` (has a trace) and the folder `data/<chapter>/illustrated/<lesson>-final/` (lecture.draft.md, improve.json, image-attempts.jsonl).
