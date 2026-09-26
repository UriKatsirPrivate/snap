#!/usr/bin/env bash
# Builds and deploys snap to Cloud Run using the project's own Dockerfile.
# Usage: PROJECT_ID=my-project CLOUDSQL_INSTANCE=project:region:instance ./scripts/deploy_cloud_run.sh
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
REGION="${REGION:-us-central1}"
# Vertex AI location used for Gemini calls -- independent of REGION, which is
# just where the Cloud Run service itself runs. Some models (e.g. lite/preview
# variants) only resolve under "global"; don't assume they match REGION.
VERTEX_LOCATION="${VERTEX_LOCATION:-global}"
SERVICE="${SERVICE:-snap}"
RECORDS_BACKEND="${RECORDS_BACKEND:-cloudsql}"
ALLOW_PUBLIC="${ALLOW_PUBLIC:-true}"
# Dedicated runtime identity (least privilege) rather than the default
# compute service account -- also the identity used for Cloud SQL IAM auth.
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-snap-run@$PROJECT_ID.iam.gserviceaccount.com}"
CLOUDSQL_DATABASE="${CLOUDSQL_DATABASE:-snap}"
CLOUDSQL_USER="${CLOUDSQL_USER:-snap-run@$PROJECT_ID.iam}"
# Gates DELETE /v1/decisions, sourced from Secret Manager (never a plain env
# var). Left unset, that endpoint just 503s -- clearing history requires
# deliberately configuring this secret, it's never on by accident.
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-snap-admin-api-key:latest}"

ENV_VARS="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$VERTEX_LOCATION,RECORDS_BACKEND=$RECORDS_BACKEND"

CLOUDSQL_FLAGS=()
if [ "$RECORDS_BACKEND" = "cloudsql" ]; then
  : "${CLOUDSQL_INSTANCE:?Set CLOUDSQL_INSTANCE (project:region:instance) when RECORDS_BACKEND=cloudsql}"
  ENV_VARS="$ENV_VARS,CLOUDSQL_INSTANCE=$CLOUDSQL_INSTANCE,CLOUDSQL_DATABASE=$CLOUDSQL_DATABASE,CLOUDSQL_USER=$CLOUDSQL_USER"
  CLOUDSQL_FLAGS=(--add-cloudsql-instances "$CLOUDSQL_INSTANCE")
fi

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$SERVICE_ACCOUNT" \
  --update-env-vars "$ENV_VARS" \
  --update-secrets "ADMIN_API_KEY=$ADMIN_API_KEY_SECRET" \
  "${CLOUDSQL_FLAGS[@]}" \
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
