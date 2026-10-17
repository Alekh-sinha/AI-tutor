# tutor — the student's teacher: plain chat and live class
Two modes on `POST /chat` (server-sent events; per-session caps; text / voice (WAV) / photo input):
- **`chat`** (`chat.py`): ChatGPT-style. Text answer (+ spoken answer when the child spoke or turned the speaker on, + at most a picture or two). No board. Works with or without an open lesson (`lesson_id` may be empty).
- **`teach`** (`agent.py`, `prep.py`): live class on a whiteboard. With a `lesson_id` it teaches that recorded lesson. With NO lesson the child's first message (text/voice/photo) says what they want to learn: `prep.py` prepares class notes
  (Google Search for facts, steps, examples, check questions; also picks related recorded lessons whose pictures can be reused), then the teacher teaches one step per turn, asking a check question and stopping.
`agent.py` tools: plan, say (voice), write_on_board, show_lesson_picture, draw_picture, clear_board. Code rules: nothing more is said after a question (`say` calls run under a lock because the model may call several in one response).
Web side: `apps/web/src/chat/` (`ChatPanel` + `useSimpleChat` = chat; `LiveClass` + `useChat` = live class; `sse.ts` shared).
Logs: `logs/tutor.jsonl` (one `turn` per request with inputs, tools used, seconds, error; plus `say`, `board-note`, `draw-picture`, `plan`, `class-prepared` (notes + related lessons), `tts-failed`, `plain-text-answer`). `GET /debug/logs/tutor`.
Symptom -> look here: "no answer / error in chat" -> `turn-failed`; "voice missing" -> `tts-failed`; "teacher talks past a question" -> `say` events after a `?`; "live class on my topic is wrong/slow" -> `class-prepared` (the notes it taught from). Tests: `tests/tutor/`.
