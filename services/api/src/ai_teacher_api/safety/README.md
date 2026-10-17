# safety: content for children

One written policy (`policy.py`) that is put into every prompt that writes, says or draws for children (live teacher, planner, figure writer, chat, lecture author, director, teacher editor, picture styles) and is the standard of the checks:

1. **Gate** (`gate.py`): a quick model call sorts every student message (text, speech or photo), every live-class topic and every teacher edit instruction into `ok / sensitive / refuse / distress` BEFORE anything is taught, planned or drawn. `refuse` and `distress` never reach the teacher agents (a polite Hindi message; distress adds Childline 1098). `sensitive` (puberty, reproduction, history of war...) is taught at textbook level with symbolic diagrams. Every non-ok verdict is stored in `flags` (admin page) and logged (`safety-flag`). If the gate itself fails the message passes (fail open): the other layers remain.
2. **Pictures**: the picture styles forbid nudity/violence; the vision check of live pictures (`live/prepare.py CHECKER`) and the picture audit of recorded lessons (`authoring/review.py`) reject unsafe pictures.
3. **Reviewers**: the lecture critic has a SAFETY item.
4. **Teacher editor**: its instructions are gated too, so the editor cannot bring unsafe content in.

The live voice cannot be filtered after she has spoken; she is protected by the gate on the topic, the policy in her instruction and the planner. Test with `tests/e2e/safety_cases.py` (13 real cases, run it after changing a prompt). Not covered: a child's spoken question in the middle of a live class is heard directly by the voice model (policy text only).
