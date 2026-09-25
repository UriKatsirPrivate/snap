# snap

A decision layer for a coding harness, backed by Gemini on GCP — the same
pattern as [keel](https://github.com/codejunkie99/keel)'s Jev integration,
ported from a local Rust/desktop app to a stateless Cloud Run service.

The host (this service) prepares a bounded set of options; Gemini picks one
or abstains; the host validates the choice before using it. See
[`docs/decision-architecture.md`](docs/decision-architecture.md) for the
full design and how it maps back to the original article/repo.

Tool execution is currently mocked (`app/tools.py:MockToolExecutor`) — this
service demonstrates the decision layer end to end; wiring it to a real
coding-agent backend is a separate step.

## Endpoints

- `GET /healthz`
- `POST /v1/decisions/route` — pick a model/provider candidate for a task
- `POST /v1/decisions/focus` — pick `inspect|implement|verify|answer` and
  get back the allowed tool bundle for that focus
- `POST /v1/execute` — run a tool through the (mocked) executor
- `GET /v1/decisions/recent` — last N decision records (for the UI)
- `GET /` — a static dashboard (`static/index.html`) to trigger route/focus
  decisions by hand and watch the decision stream

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export GOOGLE_CLOUD_PROJECT=your-gcp-project
export GOOGLE_APPLICATION_CREDENTIALS=...  # or `gcloud auth application-default login`

uvicorn app.api:app --reload
```

By default `RECORDS_BACKEND=local`, so decisions are appended to
`data/decisions.jsonl` and no BigQuery access is needed for local dev.

## Test

```bash
pytest
```

Tests use a `FakeSelector` and `LocalJsonlRecorder` — no GCP credentials or
network calls required.

## Deploy to Cloud Run

```bash
PROJECT_ID=your-gcp-project ./scripts/deploy_cloud_run.sh
```

This builds from the repo's `Dockerfile` via `gcloud run deploy --source .`
and sets `RECORDS_BACKEND=bigquery`. The service's runtime service account
needs:

- `roles/aiplatform.user` (to call Gemini via Vertex AI)
- `roles/bigquery.dataEditor` on the target dataset (or
  `roles/bigquery.admin` if you want it to create the dataset/table itself,
  which `BigQueryRecorder` will do on first write)

No API keys are needed — Vertex AI auth uses the Cloud Run service's
attached identity.
