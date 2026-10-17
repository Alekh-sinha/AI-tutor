# common — shared by every feature
`settings.py` (models, paths, env), `paths.py` (chapter folders, public lesson ids), `lesson.py` (THE lesson schema: events note/image/svg/choice/anim/clear/hide), `tts.py` (Chirp 3 HD voice),
`resilience.py` (model fallback chain on 429), `tracing.py` (Langfuse), `logsetup.py` (feature logs), `workspace.py` (lock for the image tools), `explain.py` (interview an agent about its output), `sandbox.py`.
Logs: `logs/app.jsonl`. Tests: `tests/common/`.
