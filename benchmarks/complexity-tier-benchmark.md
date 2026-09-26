# Complexity-tier classification benchmark

## Origin

This benchmark uses [LiteLLM's JEV Auto Router benchmark post](https://docs.litellm.ai/blog/jev-auto-router-benchmark)
as its starting point. That post benchmarks two classifiers -- TypeSafe's
JEV and Claude Haiku -- on a 4-tier complexity-classification task used to
route requests to different model tiers in LiteLLM's Auto Router.

**The JEV and Haiku numbers in this document are taken directly from that
post, not measured here.** Everything under "snap-tier" below was run
against this repo's own selector.

## What we ran

The same task the LiteLLM post benchmarks -- classify a task description
into one of four complexity tiers:

- `SIMPLE` -- basic lookup tasks
- `MEDIUM` -- routine drafting and localized code
- `COMPLEX` -- coupled technical work
- `REASONING` -- proofs, optimization, conflicting objectives

...but against `app/selector.py:GeminiSelector` (`gemini-2.5-flash-lite` via
Vertex AI) instead of JEV/Haiku. This lets latency, cost, and accuracy be
compared on the same task rather than across two unrelated classification
jobs (an earlier pass at this benchmark used snap's own `inspect / implement
/ verify / answer` focus taxonomy instead, which produced numbers that
looked comparable but weren't measuring the same thing -- discarded).

**Important caveat:** the LiteLLM post's own 80 test cases were never
published, only the tier descriptions and aggregate results. The 80 cases
in `scripts/benchmark_tier.py` were authored fresh from those descriptions
by us -- same task and label set, not the same literal inputs. Match rate
is therefore not a strict apples-to-apples number against JEV/Haiku; latency
and cost per call are more directly comparable, since those depend mainly
on the classifier/model itself rather than the exact wording of the input.

The LiteLLM post also disclosed that its expected-tier labels were "authored
by the same author, without independent annotation or blind adjudication."
The same is true here.

## Methodology

- **Dataset:** 80 authored cases, 20 per tier (matching the post's 20-per-tier
  split, though the post used 80 cases total across short/long/follow-up/
  tool-context/ambiguous-boundary categories -- ours doesn't subdivide
  further than tier).
- **Repeats:** each case run 3x with a seeded, per-repeat shuffle
  (`random.Random(seed + repeat).shuffle(...)`) -- 240 total calls per
  backend, matching the post's 240-call total (80 cases x 3 repeats).
- **Model:** `gemini-2.5-flash-lite` via Vertex AI (`GOOGLE_CLOUD_LOCATION=global`).
- **Backends tested:**
  - `local` -- calls `GeminiSelector.select()` in-process, no HTTP hop.
  - `http` -- POSTs to a live deployment's `POST /v1/decisions/route`,
    using the four tier names as route candidate ids (`route` accepts an
    arbitrary candidate list, so this is a legitimate use of the endpoint,
    not a repurposing hack). Latency is the server-reported
    `selector_latency_ms`, timed inside the container around just the
    Gemini call, so this machine's own network path to Vertex AI doesn't
    leak into the number.
- **Scoring:** match rate against the authored expected tier, plus
  wall-clock/server-reported latency (median, p95, min/max) and cost
  (derived from `usage_metadata` token counts x Gemini's published
  per-million-token pricing, see `GeminiSelector._PRICE_PER_MILLION_TOKENS_USD`).

## How to reproduce

```bash
# local only
GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global \
  python scripts/benchmark_tier.py --mode local

# local + against a live deployment
GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global \
  python scripts/benchmark_tier.py --mode both --url https://your-service-url
```

Each run prints a summary and writes the full per-case results to
`benchmarks/results/tier_<mode>_<timestamp>.json`.

## Results

| | JEV¹ | Haiku¹ | snap-tier (local) | snap-tier (http, deployed) |
|---|---|---|---|---|
| Task | complexity-tier classification | complexity-tier classification | complexity-tier classification | complexity-tier classification |
| Calls | 240 | 240 | 240 | 240 |
| Median latency | 126.81ms | 688.40ms | 345ms | 375ms |
| Total cost | $0.0077 | $0.1985 | $0.0020 | $0.0020 |
| Cost/call | $0.0000321 | $0.000827 | $0.0000083 | $0.0000083 |

¹ From [LiteLLM's JEV Auto Router benchmark post](https://docs.litellm.ai/blog/jev-auto-router-benchmark), not measured in this repo.

Raw results (full per-case data, confusion matrix, abstain counts):
`benchmarks/results/tier_local_20260926T110358Z.json` and
`benchmarks/results/tier_http_20260926T110609Z.json`.

### Reading these numbers

- `gemini-2.5-flash-lite` is the cheapest of the four per call, and faster
  than Haiku, but slower than JEV -- expected, since JEV is a purpose-built
  small classifier and Haiku/Gemini are general-purpose LLMs being used for
  a narrow classification task.
- Match rate (60.00% local / 62.92% http) trails both JEV (95.00%) and Haiku
  (73.75%) on this task. One call in the http run also abstained rather than
  picking a tier. Given the caveat above about differing test cases, this
  says more about how hard tier classification is from a bare one-line task
  string in general than about a precise accuracy gap between these
  specific systems.
- `local` vs `http` match-rate and latency differences are consistent with
  normal run-to-run LLM sampling variance and network-path differences
  (this dev machine's route to Vertex AI vs the deployed container's), not a
  real behavioral difference in the model.
