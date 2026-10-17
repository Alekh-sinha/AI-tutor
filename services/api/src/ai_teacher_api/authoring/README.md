# authoring — Agent 1 (illustrated lecture) + reviewers + editor
`illustrator.py` (Agent 1's instruction and picture tools: generate_image / edit_image / view_picture; shared image state), `run_illustrate.py` (first draft workflow), `review.py` (code checks: pictures exist/unused,
questions, length, attention gaps; the reviewer's prompt and audit schema; per-picture 640 px views), `edit_loop.py` (reviewers x2 -> findings -> separate editor; picture findings need both passes; frozen pictures),
`run_improve.py` (re-run the loop on an existing lecture), `explain.py` (interview Agent 1), `run_fix.py` (the fix-loop experiments).
Logs: `logs/authoring.jsonl` (events `re-improve`, `explanation`). Per-lesson evidence in `data/<chapter>/illustrated/<lesson>-final/` (audit-*.json = what each reviewer pass saw, image-attempts.jsonl).
Symptom -> look here: "wrong/ugly picture", "lecture too long/short", "reviewer keeps flagging something" -> the audit-*.json of that round, then `review.py` (LECTURE_CRITIC) / `illustrator.py` (INSTRUCTION, tool docstrings). Tests: `tests/authoring/`.
