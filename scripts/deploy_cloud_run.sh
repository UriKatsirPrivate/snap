#!/usr/bin/env bash
# Builds and deploys snap to Cloud Run using the project's own Dockerfile.
# Usage: PROJECT_ID=my-project ./scripts/deploy_cloud_run.sh
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
REGION="${REGION:-us-central1}"
# Vertex AI location used for Gemini calls -- independent of REGION, which is
# just where the Cloud Run service itself runs. Some models (e.g. lite/preview
# variants) only resolve under "global"; don't assume they match REGION.
VERTEX_LOCATION="${VERTEX_LOCATION:-global}"
SERVICE="${SERVICE:-snap}"
RECORDS_BACKEND="${RECORDS_BACKEND:-bigquery}"
ALLOW_PUBLIC="${ALLOW_PUBLIC:-true}"

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$VERTEX_LOCATION,RECORDS_BACKEND=$RECORDS_BACKEND" \
  --no-allow-unauthenticated

# Cloud Run resets the invoker policy on every deploy, dropping any earlier
# public grant -- reapply it here (default on) so the service doesn't need a
# manual follow-up step. Set ALLOW_PUBLIC=false to keep it private instead.
if [ "$ALLOW_PUBLIC" = "true" ]; then
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --member=allUsers \
    --role=roles/run.invoker
fi
