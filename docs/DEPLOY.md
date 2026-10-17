# Deploying Seekho Saathi (Google Cloud Run)

One container = the built web app + the API (`ai_teacher_api.server:root`). One address, no cross-site settings.

## Pieces
| what | where |
|---|---|
| app | Cloud Run service `seekho-saathi` (public), image `us-central1-docker.pkg.dev/automation-ai-507911/seekho/seekho:<tag>`, built with `gcloud builds submit` |
| test copy | Cloud Run service `seekho-saathi-test` (NOT public: needs an identity token; has `AUTH_DEV_LOGIN=1`, own bucket and Firestore prefix) |
| files | buckets `automation-ai-507911-seekho-data` (prod) / `-seekho-test`; mirrored from local disk (`common/persist.py`): restored at start, pushed every 30 s, on shutdown and after each job |
| users, credit, ledger, requests, flags | Firestore (default database), collections prefixed `seekho_` (prod) / `seekho_test_` (test); the project is shared with other apps, so always keep the prefix |
| secrets | Secret Manager: `seekho-session-secret`, `seekho-langfuse-*` |
| identity | service account `seekho-saathi@...` (aiplatform.user, datastore.user, serviceusage consumer, logging, secret accessor, storage admin on its buckets) |

## Settings that matter (and why)
- `--max-instances 1 --min-instances 1`: live-class rooms, running jobs and the hand-over of the floor live in memory. Two instances would split a class. Do not raise without moving that state out (Redis / Firestore).
- `--no-cpu-throttling`: lesson generation (20-30 min) and live classes run on background work between requests.
- `--timeout 3600`: the longest allowed request, for the live-class WebSocket. uvicorn pings every 20 s (`--ws-ping-interval`), SSE streams send `: ping` every 15 s (`common/sse.py`). Nothing sits in front (no Firebase Hosting rewrite, which cuts requests at 60 s).
- `--memory 4Gi`: the container disk is in memory; a chapter with pictures is tens of MB.
- No `--workers`: one process.
- A restart loses in-flight background jobs (generation resumes by stage when started again) and ends running live classes (children see "connection lost").

## Environment
`AUTH_MODE=on`, `STORE=firestore`, `STORE_PREFIX`, `DATA_BUCKET`, `GOOGLE_CLIENT_ID` (OAuth web client, authorised JavaScript origin = the service URL), `SESSION_SECRET`, `ADMIN_EMAILS` (default alekh.sinha09@gmail.com), `START_CREDIT_USD` (10), `DAILY_CAP_USD` (5), Langfuse keys. Never set `AUTH_DEV_LOGIN` on the public service: it lets anybody sign in as any email.

## Commands
```
# build
gcloud builds submit --tag us-central1-docker.pkg.dev/automation-ai-507911/seekho/seekho:vN --project automation-ai-507911 --region us-central1 .
# seed the bucket with the first book and the free lessons (once)
cd services/api && uv run python ../../deploy/seed_bucket.py /tmp/seed && gcloud storage rsync -r /tmp/seed gs://automation-ai-507911-seekho-data
# deploy: see deploy/deploy.sh
```
## Reading what happened
`GET /api/debug/logs/<feature>` (admin) or Cloud Logging; Langfuse traces carry a hashed user id.
