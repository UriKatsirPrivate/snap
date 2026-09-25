# Decision architecture

snap ports the decision-layer pattern from [keel](https://github.com/codejunkie99/keel)
onto GCP: a stateless Cloud Run service in front of Gemini, instead of a
local desktop app in front of Laya/Jev. The rule stays the same: **a model
can suggest the next move; the host still owns the move.**

Note: keel's "Jev" mode is a hosted third-party decision service
("TypeSafe") requiring an API credential, not a model we can call directly
— and the linked "jev-engineering" write-up includes a file explicitly
packaged as an integration prompt for a coding assistant, which is a
prompt-injection red flag rather than trustworthy documentation. snap does
not integrate with it. Gemini fills the "hosted decision model" role here;
keel's Laya (a local Core ML selector) has no equivalent in snap yet.

## Two decision points

### 1. Route selection — `POST /v1/decisions/route`

Given a task and a host-prepared list of candidates (e.g. which
model/provider should handle it), Gemini picks one id or abstains.

- A `pinned_route_id` bypasses the selector entirely — user intent always
  wins, and this mirrors keel's rule that pinned routes and running sessions
  are never silently rerouted.
- The selector only ever sees candidate ids and context, never raw
  credentials or arbitrary instructions.
- The host re-validates the returned id is actually one of the candidates
  offered before using it. An invalid or abstained result falls back to an
  explicit `fallback_route_id` if one was given; otherwise the decision is
  `abstained` and it's the caller's job to handle that.

### 2. Focus selection — `POST /v1/decisions/focus`

Given a task/session, Gemini picks one of `inspect | implement | verify |
answer`. Each focus maps to a fixed, host-defined tool bundle
(`app/tools.py:TOOL_BUNDLES`). `answer` always gets zero tools — the same
guardrail keel uses so the selector can never grant itself execution
authority.

The host filters the bundle against `available_tools` supplied in the
request, so a tool that no longer exists (renamed, removed) is dropped
before dispatch rather than causing a bad call downstream.

## What the selector cannot do

- It cannot invent a candidate id or focus id that wasn't offered.
- It cannot grant tool permission — `/v1/execute` checks the tool name
  against the known bundles independently of any single decision, and a
  real deployment would still gate this behind whatever permission system
  wraps tool execution.
- It cannot see or affect the other decision point — route and focus
  selection are separate calls with separate validation.

## Decision records

Every route/focus decision writes a `DecisionRecord`
(`app/schemas.py:DecisionRecord`) capturing what was offered, what the
selector returned, whether the host validated it, whether a fallback was
used, and the final choice. Records are not chain-of-thought — just enough
structure to replay a decision later and ask whether a prompt/model/policy
change actually helped, the same evaluation loop the keel article proposes.

Two recorders are provided (`app/records.py`):

- `LocalJsonlRecorder` — appends JSON lines locally, used by default and in
  tests, no GCP credentials required.
- `BigQueryRecorder` — streams into BigQuery (creating the dataset/table on
  first use if missing), for the Cloud Run deployment.

Switch via `RECORDS_BACKEND=local|bigquery`.

## Execution is mocked, on purpose

`app/tools.py:MockToolExecutor` returns a fake result for any tool in a
known bundle. This lets the decision layer, validation, and logging be
exercised end to end without a real coding-agent backend wired in yet.
Swapping in a real executor means implementing `ToolExecutor.execute` and
wiring it into `app/api.py:get_tool_executor` — nothing else in the
decision/validation path needs to change, which is the point of keeping
selection and execution as separate interfaces.
