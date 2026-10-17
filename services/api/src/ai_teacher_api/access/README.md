# access: who may use the AI, and who pays

Everything about accounts, credit and visibility. Logs: `logs/app.jsonl` (events `login`, `request`, `request-decided`, `grant`, `charge-failed`, `class-stopped-credit`).

| file | job |
|---|---|
| `auth.py` | Google sign-in (ID token checked with Google's keys) -> our signed session cookie (`ss_session`, 7 days). Dependencies `optional_user` / `active_user` / `admin_user`. `AUTH_MODE=off` (default, local): everybody is the admin `dev@local`. `AUTH_MODE=on`: sign-in needed. `AUTH_DEV_LOGIN=1` allows `GET /auth/dev?email=` for tests only. |
| `credits.py` | users, balance, ledger. Money is micro-dollars. `check()` before paid work, `spend()` after. Statuses: `pending` (just signed in: free lessons only) -> `active` (admin approved, has credit) / `blocked`. Daily cap (IST day, default $5). Spends are atomic increments; with batching (deployed) they are summed and written once a second per user, and `check()` counts what is still waiting. |
| `pricing.py` | what a call costs (list prices + 15% margin; unknown models are charged like Pro, never free). |
| `usage.py` | the signed-in user travels in a context variable into every model call, including background jobs; the google-genai SDK is wrapped once (`install()`): check before, charge after. TTS is charged in `common/tts.py`, the live session in `live/session.py::_meter` (to the host). |
| `store.py` | tiny document store: `MemoryStore` (tests, local) and `FirestoreStore` (deployed, collections prefixed by `STORE_PREFIX`). |
| `ownership.py` | a user's chapters have the id prefix `u<hash of email>-`; `chapter_dir()` refuses other people's chapters. |
| `library.py` | `/lessons/index.json`, `/lessons/<id>.json`, `/audio/<id>.mp3` with visibility rules; the FREE lessons (`data/public-lessons.json`) are open to everyone, even without sign-in. |
| `routes.py` | `/auth/*`, `/me`, `/access/request`, `/credit/request`, `/admin/*` (overview, users, ledger, grant, cap, block, requests, flags, free lessons). |

Admin email: env `ADMIN_EMAILS` (default alekh.sinha09@gmail.com). Start credit `START_CREDIT_USD` (10), daily cap `DAILY_CAP_USD` (5). Requests are decided by the admin once a day after 9 PM IST; every message to users says so.

Tests: `tests/access/` (unit + HTTP flows), `tests/e2e/access_flow.py` (browser: visitor, request, approval, charge, refusal, limit dialog, isolation), `tests/e2e/access_live.py` (a live class: metering, ends kindly), `tests/e2e/firestore_store.py` (real Firestore, concurrent spends).
