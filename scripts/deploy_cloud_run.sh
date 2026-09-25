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

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$VERTEX_LOCATION,RECORDS_BACKEND=$RECORDS_BACKEND" \
  --no-allow-unauthenticated
