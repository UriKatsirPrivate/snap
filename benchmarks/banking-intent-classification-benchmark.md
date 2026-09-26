# Banking-intent classification benchmark

## Origin

This benchmark uses [this Towards Data Science article on "a new kind of
model for AI decision-making"](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/)
as its starting point. That article covers TypeSafe's `jev-latest` (the same
product behind the JEV Auto Router benchmark this repo's other benchmark
reproduces, see `benchmarks/complexity-tier-benchmark.md`) and reports a
benchmark against two GPT-5.6 variants -- `gpt-5.6-terra` and
`gpt-5.6-luna` -- on intent classification.

**The jev-latest/gpt-5.6-terra/gpt-5.6-luna numbers in this document are
taken directly from result tables in that article (screenshots of its
pandas output), not measured here.** Everything under "snap" below was run
against this repo's own selector.

**Caveat on the source itself:** the article's prose was originally read via
an automated web-fetch summarizer, which mischaracterized a few things later
corrected against the article's actual result tables -- it described "Terra"
and "Luna" as separate named OpenAI models (they're `gpt-5.6-terra` /
`gpt-5.6-luna`, variants of one underlying model) and reported "~40x more
output tokens than Luna" for Jev, when the actual table numbers give
828,290 / 44,261 ≈ **18.7x**. Some other terminology it reported (a training
method called "RLCD," structured-question primitives named
"Choice/Score/Noul") still hasn't been independently verified and should be
treated as "what the tool extracted," not confirmed fact, if referenced in
the eventual article. The result-table numbers below are the article's
actual reported figures, not summarizer output.

## What we ran

The article's benchmark uses [PolyAI's banking77 dataset](https://github.com/PolyAI-LDN/task-specific-datasets)
(public, CC BY 4.0): real customer-support utterances, each labeled with one
of 77 banking intents (e.g. `card_arrival`, `age_limit`,
`apple_pay_or_google_pay`). A snapshot of its test split (3080 examples, 40
per class) is committed at `benchmarks/data/banking77_test.csv`, fetched
from that repo's `banking_data/test.csv`.

We classify the same utterances against `app/selector.py:GeminiSelector`
(`gemini-2.5-flash-lite` via Vertex AI), giving it the intent names as the
option list -- same mechanism as `scripts/benchmark_tier.py`.

## Real finding: a production ceiling, not a benchmark-only issue

The article's task is 77-way classification. Testing this against
`GeminiSelector` directly, requests **fail outright above ~53 options**:

```
n=50: OK
n=52: OK
n=53: OK
n=54: FAIL -- 400 INVALID_ARGUMENT: "The specified schema produces a
              constraint that has too much branching for serving."
n=60, 65, 70, 77: FAIL (same error)
```

This is Vertex AI rejecting `GeminiSelector`'s constrained-enum
`response_schema` (`app/selector.py:GeminiSelector.select`, the
`text/x.enum` + `enum: [...]` mode added for speed -- see `NOTES.md`'s
"Enum-mode structured output" section) once the option list gets large
enough. It reproduces with generic short placeholder strings too, but not
until a higher count -- 77 generic `option_N` strings all abstained
successfully, while 77 *real* banking77 category names failed at the same
count. The schema's total size/complexity, not just the number of options,
appears to drive the limit, so **the exact threshold is content-dependent,
not a fixed enum count** -- 53-54 is where it landed for this specific
dataset's category name strings, not a general constant.

**This means the full 77-class task cannot run against `GeminiSelector`'s
enum-mode path, full stop -- not a workaround, a real capacity ceiling in
that decoding approach.** The first measurement of this benchmark (below,
"Initial run") deliberately did not patch around it and used a 50-class
subset instead. A follow-up run (see "Follow-up: the actual 77-class task"
below) later added a temporary fallback specifically to measure the real
77-class task, then reverted it -- the ceiling described above is the
current, permanent state of `app/selector.py`.

## Initial run: 50-class subset

Because the ceiling above wasn't cleared yet at this point, this first run
used **the first 50 of the 77 classes** (alphabetical by category name)
instead of the full 77 -- comfortably under the confirmed working ceiling.
**This made accuracy not directly comparable to the article's 77-class
numbers**: fewer classes is a strictly easier classification task (fewer
confusable neighbors, higher baseline accuracy), so a higher or lower match
rate here wasn't evidence of a better or worse classifier than
Jev/Terra/Luna on their own task. Superseded by the 77-class follow-up run
below, but kept here as the historical record of what was actually run and
why.

The article's own tables don't report cost ($) for jev-latest/gpt-5.6-terra/
gpt-5.6-luna, only accuracy + token counts (n=1000 answered) and latency
(n=100 calls, mean/median/p90/min/max). So unlike
`complexity-tier-benchmark.md`, there's no cost row to place snap's numbers
next to; latency and token counts are compared directly below, cost is
reported standalone for snap only.

### Methodology (initial run)

- **Dataset:** banking77 test split, first 50 of 77 classes (alphabetical),
  7 examples sampled per class (stratified, seeded) = 350 cases.
- **Repeats:** 1 pass (no repeated calls per case, unlike the tier
  benchmark's 3x) -- single pass was judged sufficient given the larger
  case count relative to the tier benchmark's 80.
- **Model:** `gemini-2.5-flash-lite` via Vertex AI (`GOOGLE_CLOUD_LOCATION=global`).
- **Backends tested:**
  - `local` -- calls `GeminiSelector.select()` in-process.
  - `http` -- POSTs to a live deployment's `POST /v1/decisions/route`,
    using the 50 intent names as route candidate ids. Latency is the
    server-reported `selector_latency_ms`.
- **Scoring:** match rate against the ground-truth banking77 label, plus
  latency (median, p95, min/max) and cost (from `usage_metadata` token
  counts x Gemini's published per-million-token pricing).

### Results (initial run)

**Accuracy and tokens** (article: n=1000 answered, 77-class; snap: n=350, **50-class**):

| Model | Answered | Correct | Accuracy | 95% CI | Input tokens | Output tokens |
|---|---|---|---|---|---|---|
| `gpt-5.6-luna`¹ | 1000 | 862 | 86.2% | [83.92%, 88.20%] | 474,552 | 44,261 |
| `gpt-5.6-terra`¹ | 1000 | 839 | 83.9% | [81.49%, 86.05%] | 474,552 | 21,562 |
| `jev-latest`¹ | 1000 | 790 | 79.0% | [76.37%, 81.41%] | 1,040,811 | 828,290 |
| snap (local) | 350 | 268 | 76.57% | not computed | not captured | not captured |
| snap (http, deployed) | 350 | 265 | 75.71% | not computed | not captured | not captured |

**Latency** (ms; article: n=100 calls; snap: n=350):

| | `jev-latest`¹ | `gpt-5.6-luna`¹ | `gpt-5.6-terra`¹ | snap (local) | snap (http, deployed) |
|---|---|---|---|---|---|
| Calls | 100 | 100 | 100 | 350 | 350 |
| Mean | 690 | 1190 | 1190 | 400 | 394 |
| Median | 670 | 1010 | 1030 | 374 | 385 |
| P90 | 790 | 2010 | 1630 | 481 | 454 |
| Min | 580 | 600 | 780 | 266 | 225 |
| Max | 1180 | 3920 | 4260 | 1627 | 1045 |

Snap's cost (not reported by the article for any of its three models):
$0.0260 total / $0.0000743 per call, both backends (350 priced calls each).

¹ From result tables (screenshots of the article's own pandas output), not
measured here. **Not the same task as the snap rows in this section** --
77-class vs 50-class, and different sample sizes.

Raw results: `benchmarks/results/banking77_local_20260926T113705Z.json` and
`benchmarks/results/banking77_http_20260926T114036Z.json`.

## Follow-up: the actual 77-class task

To measure the real task the article ran (not a 50-class stand-in), a
temporary fallback was added to `app/selector.py:GeminiSelector.select()`:
above `_MAX_ENUM_OPTIONS` (50, a safety margin under the confirmed ~53-54
ceiling), it drops the constrained-enum schema and falls back to free-text
generation, asking the model to echo one option's exact text (or an abstain
sentinel) and validating the echoed string against the option list.
Deployed to Cloud Run, smoke-tested at 77 options (worked cleanly, 6/6
correct on a spot check), then used for the run below. **This fallback was
reverted immediately afterward** (`git checkout -- app/selector.py`,
redeployed) -- it does not exist in the codebase as it stands, and the live
ceiling is back to ~50 options. Reproducing this exact run would require
re-adding that fallback first; it is not just a CLI flag away like the
50-class run above.

Trade-off of the fallback itself: free-text + string-match validation is
inherently less reliable than constrained enum decoding (the model could in
principle paraphrase or add filler instead of echoing exactly), so this was
a deliberate one-off measurement tool, not something being kept as a
permanent second code path.

### Methodology (follow-up run)

- **Dataset:** banking77 test split, all 77 classes, 13 examples sampled
  per class (stratified, seeded) = 1001 cases -- chosen to land close to
  the article's n=1000 accuracy sample size.
- **Repeats:** 1 pass.
- **Model:** `gemini-2.5-flash-lite` via Vertex AI, same as above.
- **Backend:** `http` only, against the deployed service (this run was
  deliberately not also run `local`, since the point was measuring the real
  production endpoint's behavior at full scale).
- **Scoring:** same as the initial run -- match rate, latency, cost.

### Results (follow-up run) -- the real apples-to-apples comparison

| | `jev-latest`¹ | `gpt-5.6-luna`¹ | `gpt-5.6-terra`¹ | snap (77-class, http) |
|---|---|---|---|---|
| Cases | 1000 | 1000 | 1000 | 1001 |
| Accuracy | 79.0% | 86.2% | 83.9% | 74.93% |
| Abstained | not disclosed | not disclosed | not disclosed | 1.90% (19/1001) |
| Median latency | 670ms | 1010ms | 1030ms | 341ms |
| Cost | not disclosed | not disclosed | not disclosed | $0.0703 total, $0.0702/1000 calls |

¹ From the article, not measured here.

Raw results: `benchmarks/results/banking77_http_20260926T124617Z.json`.

Unlike the initial run, this **is** a genuine same-class-count comparison:
snap is faster than all three article systems (341ms vs 670-1030ms median)
but less accurate than all three (74.93% vs 79-86%) -- a real, if modest,
accuracy gap on the actual task, not an artifact of an easier 50-class
subset.

## How to reproduce

The 50-class initial run reproduces directly against current `main`:

```bash
# local only, default 50-class cap and 7 samples/class
GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global \
  python scripts/benchmark_banking77.py --mode local

# local + against a live deployment
GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global \
  python scripts/benchmark_banking77.py --mode both --url https://your-service-url
```

`--max-classes` (default 50) and `--sample-per-class` (default 7) control
the dataset slice.

The 77-class follow-up run does **not** reproduce as-is -- `--max-classes 77`
alone will hit the same 400 error described above, since the free-text
fallback that made it work has been reverted. Re-running it requires
re-adding that fallback to `GeminiSelector.select()` first (see "Follow-up"
above for what it did), then:

```bash
GOOGLE_CLOUD_PROJECT=your-project GOOGLE_CLOUD_LOCATION=global \
  python scripts/benchmark_banking77.py --mode http --url https://your-service-url \
  --sample-per-class 13 --max-classes 77
```

## Reading these numbers

- The headline finding isn't just the accuracy comparison -- it's that
  **`GeminiSelector`'s default constrained-decoding path has a real ceiling**
  somewhere around 53-54 options for realistic category-name content, and
  clearing it for a genuine 77-class measurement required a temporary,
  deliberately-reverted fallback rather than a permanent capability.
- On the real 77-class task (the follow-up run), snap is faster but less
  accurate than all three article systems -- 74.93% vs 79-86% accuracy,
  341ms vs 670-1030ms median latency.
- On the easier 50-class task (the initial run), snap landed at 75-77%
  accuracy with a 2-3% abstain rate -- close to its 77-class accuracy
  despite the easier task, suggesting the accuracy gap versus
  Jev/Terra/Luna isn't purely a function of class count.
- `jev-latest` is the fastest of the three article models (670ms median)
  despite generating ~18.7x more output tokens than `gpt-5.6-luna` --
  consistent with it being a purpose-built small classifier rather than a
  general-purpose LLM, similar to the latency/cost pattern seen in
  `complexity-tier-benchmark.md`.
- `local` vs `http` differences in the initial run (76.57% vs 75.71%
  accuracy, 374ms vs 385ms median latency) are consistent with normal LLM
  sampling variance and network-path differences, not a real behavioral
  difference.
