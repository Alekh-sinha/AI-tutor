#!/bin/bash
# usage: deploy/deploy.sh <test|prod> <image-tag> [google-client-id]
set -e
P=automation-ai-507911; R=us-central1; ENV=$1; TAG=$2; CID=${3:-}
IMG=$R-docker.pkg.dev/$P/seekho/seekho:$TAG
SECRETS="SESSION_SECRET=seekho-session-secret:latest,LANGFUSE_PUBLIC_KEY=seekho-langfuse-public-key:latest,LANGFUSE_SECRET_KEY=seekho-langfuse-secret-key:latest,LANGFUSE_BASE_URL=seekho-langfuse-base-url:latest"
if [ "$ENV" = test ]; then
  NAME=seekho-saathi-test; EXTRA="--no-allow-unauthenticated"; VARS="DATA_BUCKET=$P-seekho-test,STORE_PREFIX=seekho_test_,AUTH_DEV_LOGIN=1"
else
  NAME=seekho-saathi; EXTRA="--allow-unauthenticated"; VARS="DATA_BUCKET=$P-seekho-data,STORE_PREFIX=seekho_"
fi
[ -n "$CID" ] && VARS="$VARS,GOOGLE_CLIENT_ID=$CID"
gcloud run deploy $NAME --image $IMG --project $P --region $R --service-account seekho-saathi@$P.iam.gserviceaccount.com \
  --cpu 2 --memory 4Gi --timeout 3600 --min-instances 1 --max-instances 1 --concurrency 80 --no-cpu-throttling --execution-environment gen2 --port 8080 \
  --set-env-vars "$VARS" --set-secrets "$SECRETS" $EXTRA
