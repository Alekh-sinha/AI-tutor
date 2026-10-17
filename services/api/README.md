# Seekho Saathi API

FastAPI backend (Google ADK agents, Gemini on Vertex AI). Project overview, setup and architecture: see the [root README](../../README.md).

- Run: `AUTH_MODE=off uv run uvicorn ai_teacher_api.server:root --port 8001`
- Tests: `uv run pytest -q` (no network needed)
- Code is organised by feature in `src/ai_teacher_api/<feature>/`; each folder has its own README.
- Logs: every feature writes JSONL events to `logs/<feature>.jsonl`; `GET /debug/logs/<feature>` reads them. Symptom to feature map: `../../docs/DEBUGGING.md`.
