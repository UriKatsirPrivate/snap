# How Many Options Does It Take to Beat a Purpose-Built Router?

*Benchmarking Gemini 2.5 Flash-Lite against TypeSafe's JEV and GPT-5.6 inside snap, a GCP-native decision layer*

> **Before anything else:** the benchmark numbers in this article are the result of my own, independent testing. They are not run, reviewed, sponsored, or endorsed by Google, and nothing here should be read as an official Gemini or Vertex AI benchmark. Treat these numbers the way you'd treat any single engineer's homegrown test suite — directionally useful, not a certification.

I recently built [snap](https://github.com/UriKatsirPrivate/snap), a small Cloud Run service that acts as a decision layer: instead of a caller hardcoding "use model X" or "use option Y," it hands a bounded list of options to Gemini, gets back one choice or an abstention, and the host still owns what actually happens next. It's a GCP-flavored take on the same idea behind TypeSafe's JEV router in LiteLLM's Auto Router — a small model, sitting in front of bigger decisions, deciding which one to make.

Once it worked, the obvious question was: how does a general-purpose LLM doing this job compare to routers built specifically for it? I ran two benchmarks against public numbers from two outside sources — [LiteLLM's JEV Auto Router post](https://docs.litellm.ai/blog/jev-auto-router-benchmark), and a [Towards Data Science article](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/) benchmarking JEV against two GPT-5.6 variants — and the results split cleanly along one axis: **how many options are on the table.**

This article is about latency. A routing decision only matters if it's fast enough not to become the bottleneck in whatever it's routing, so that's the axis I care about here.

## TL;DR

- At a small number of options (a 4-way classification task), a purpose-built router like JEV is roughly 3x faster than Gemini — expected, since JEV is built for exactly this narrow job, and Gemini is a general-purpose LLM paying full inference overhead for a tiny decision.
- At a large number of options (a 77-way classification task), that latency gap inverts. Gemini's constrained-decoding response stays essentially flat regardless of option count, while JEV's own latency grew roughly 5x between the two tasks — putting Gemini ahead.
- As the option set grows from a handful to dozens, Gemini's latency disadvantage against purpose-built routers doesn't just shrink — it inverts. Reach for a dedicated router at small option counts; a general-purpose LLM with constrained decoding becomes competitive, and here faster, once the option set gets large.
- Running everything through Vertex AI also means the classified data — including real customer text, in the 77-option benchmark — never leaves your GCP project. For anyone already committed to GCP, that's a second reason to prefer Gemini once the latency gap closes.

## What snap's Decisions layer actually does

Before the numbers, it's worth being concrete about what's being measured, because "LLM router" covers a lot of different designs.

snap exposes two decision kinds through `POST /v1/decisions/route` and `POST /v1/decisions/focus`. Route picks among host-supplied candidates (models, providers, whatever the caller defines); Focus picks one of four fixed tool bundles — `inspect`, `implement`, `verify`, `answer` — for a single turn of work. Both go through the same `GeminiSelector`, and both follow the same rule: **the model suggests, the host decides.**

Concretely, that means:

- The selector only ever sees candidate IDs and context — never credentials, never the ability to call anything itself.
- Gemini is constrained to a structured enum response (`response_mime_type="text/x.enum"`, schema = `[*options, "__ABSTAIN__"]`) with `thinking_budget=0` and a 16-token output cap. It cannot return a string that isn't one of the offered options — there's no invented-ID failure mode to defend against downstream.
- The host re-validates the returned ID against the original candidate list before using it. If the pick is invalid, or Gemini abstains, execution falls back to a caller-supplied `fallback_route_id`; with no fallback, the decision comes back as `abstained`.
- Some decisions shouldn't go through the model at all. A caller can pass a `pinned_route_id` to force a specific choice deterministically — the selector is skipped entirely, and the response is just that pinned choice. This is for cases where the decision needs to be certain (a kill switch, a forced override, a known-good default), not delegated to a model that might abstain or pick something else.
- Every decision — kind, offered options, Gemini's raw pick, final validated choice, status, latency, cost — gets logged asynchronously after the response is already sent, so recording never adds latency to the caller.

There's a small dashboard on top of this (the "Decisions" tab) that's mostly useful for watching the thing work: a live stream of every decision with per-row status badges (accepted / fallback / abstained / pinned / rejected), a rolling latency/cost line, and a clear-history control for resetting between test runs. None of that is the interesting part of this article — the interesting part is what happens when you point `GeminiSelector` at two very different classification tasks and measure it against systems built for exactly that job.

## Benchmark 1: four options, authored fresh

The first comparison uses [LiteLLM's JEV Auto Router benchmark](https://docs.litellm.ai/blog/jev-auto-router-benchmark) as a starting point: classify a task description into one of four complexity tiers — `SIMPLE`, `MEDIUM`, `COMPLEX`, `REASONING` — used to route requests to different model tiers. The post's own 80 test cases were never published, so I authored 80 fresh cases from its tier descriptions, ran each 3x (240 calls total, matching the post's call count), and scored `GeminiSelector` the same way. Latency and cost per call are directly comparable to the post's numbers, since both depend on the model itself rather than the exact wording of the input.

| | JEV¹ | snap (Gemini) | Haiku¹ |
|---|---|---|---|
| Calls | 240 | 240 | 240 |
| Median latency | **126.81ms** | 375ms | 688.40ms |
| Cost/call | $0.0000321 | **$0.0000083** | $0.000827 |

¹ From LiteLLM's post, not measured by me.

On latency, JEV wins clearly: roughly 3x faster than Gemini here. This is the expected outcome, and it's worth saying plainly: JEV is a purpose-built small classifier, and Gemini is a general-purpose LLM being asked to do a narrow job. Even with `thinking_budget=0` and a 16-token cap, Gemini is still paying the overhead of a full LLM inference call — network round-trip to Vertex AI, model loading path, tokenization — for a decision that's genuinely tiny: one of four labels, from a one-line task description. For decisions this small and this fast, a dedicated router is going to win on latency, and by a wide margin. That's not a knock on Gemini; it's a mismatch between the tool and the job.

Cost is the one place Gemini pulls ahead outright: at $0.0000083/call it's roughly 4x cheaper than JEV and two orders of magnitude cheaper than Haiku, since `gemini-2.5-flash-lite` is priced and capped for exactly this kind of short-output task.

## Benchmark 2: seventy-seven options

The second comparison is based on a [Towards Data Science article](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/) benchmarking JEV against `gpt-5.6-terra` and `gpt-5.6-luna` on intent classification, using [PolyAI's banking77 dataset](https://github.com/PolyAI-LDN/task-specific-datasets) — real customer-support utterances, each labeled with one of 77 banking intents (`card_arrival`, `age_limit`, `apple_pay_or_google_pay`, and so on). I pointed `GeminiSelector` at the same dataset, giving it the 77 intent names as the option list, and ran it against a deployed instance to get a genuine 77-class, same-scale comparison against the article's numbers:

| | snap (Gemini) | JEV¹ | GPT-5.6-luna¹ | GPT-5.6-terra¹ |
|---|---|---|---|---|
| Cases | 1001 | 1000 | 1000 | 1000 |
| Median latency | **341ms** | 670ms | 1010ms | 1030ms |
| Cost | $0.0702/1000 calls | not disclosed | not disclosed | not disclosed |

¹ From the Towards Data Science article's result tables, not measured by me.

The latency ranking flips completely. JEV was 3x faster than Gemini at four options. At 77 real options, Gemini is now the fastest system on the table — faster than JEV, and roughly a third the latency of both GPT-5.6 variants. JEV's own latency roughly quintupled going from the 4-tier task to the 77-class task (127ms → 670ms), while Gemini's stayed essentially flat (345–375ms → 341ms). A constrained-decoding approach that just picks a token out of a fixed schema doesn't get meaningfully slower as the option set grows the way a token-generating classifier apparently does — it's answering "which of these 77 things" with the same one-token response it used for "which of these 4 things."

## The other reason to reach for Gemini: it never leaves GCP

Everything above is about latency. There's a second axis that doesn't show up in either table: where your data goes.

JEV, GPT-5.6-terra, and GPT-5.6-luna are all third-party APIs — calling them means shipping whatever you're classifying (a task description, a customer's actual support message) to an external vendor. `GeminiSelector` calls Vertex AI, which means the request stays inside your own GCP project and region. If you're already running your stack on GCP — and especially if you're in banking, healthcare, or anywhere else with real constraints on where customer data is allowed to travel — that's not a minor convenience; it's the difference between "compliant by construction" and "another vendor to put in front of legal." The banking77 dataset is a pointed example: it's exactly the kind of customer-utterance data a bank would have real reasons not to hand to an outside API, benchmark or not.

This is the piece I'd weigh most heavily for anyone deciding between these options in practice. At small option counts, a few hundred milliseconds of latency difference is a real cost, and JEV wins it outright. But once that latency gap closes or inverts — which the 77-class numbers above show it does — sending customer data outside your compliance boundary stops buying you anything and starts being a straightforwardly bigger cost.

## Where this is actually useful

Putting the two findings together — small option sets favor purpose-built routers on latency, large ones favor Gemini; and GCP-native means no data egress — a few concrete use cases fall out:

- **Support-ticket or intent routing across a large taxonomy.** Banking77-style classification — dozens of intents, real customer text — is close to a best case for this approach: large option set (where Gemini's latency is competitive or better), and often exactly the kind of data (customer support content, sometimes PII-adjacent) you'd rather not route through a third-party classifier.
- **Model/tool selection in an agent harness with a genuinely large candidate set** — e.g., routing a request across a large internal catalog of specialized models or plugins, not just three or four. This is where the latency crossover matters most: at scale, the "smart general-purpose model" stops being the slow option.
- **Compliance-constrained classification pipelines** — document categorization, ticket triage, anything with a large, well-defined label set inside a regulated industry that's already standardized on GCP. The value here is not needing a new vendor and a new data-flow review to add a routing layer.
- **Where it's the wrong tool:** anything genuinely small and latency-critical, with no data-residency constraint — like snap's own `Focus` decision, choosing among four fixed tool bundles. That's a four-option decision, squarely in JEV's territory in the numbers above, and if JEV's ~125ms matters more than staying in-cloud, a purpose-built router is the better call there. I use Gemini for it anyway in snap because the whole system is intentionally GCP-only, but I'd say that plainly to anyone copying the pattern: know which regime your decision falls into before picking the tool.

## The caveats, stated plainly

- The JEV, GPT-5.6-terra, GPT-5.6-luna, and Haiku numbers throughout this article are taken from two external sources — [LiteLLM's JEV Auto Router post](https://docs.litellm.ai/blog/jev-auto-router-benchmark) and a [Towards Data Science article](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/) — not measured by me. Only the "snap (Gemini)" rows were run in my own environment.
- The 4-tier benchmark's test cases were authored by me from the LiteLLM post's tier descriptions, not the post's original (unpublished) cases. Latency and cost per call are still directly comparable, since they depend on the model itself rather than the exact wording of the input.
- The 77-class banking77 comparison is a genuine same-task, same-scale comparison against the article's numbers.
- None of this is an official or Google-affiliated benchmark of Gemini, Vertex AI, or any other product named here. It's one engineer's test harness, published so the methodology and raw results are inspectable — not a claim about how these systems perform in general.

Full methodology, raw result files, and reproduction commands for both benchmarks are in the [repo](https://github.com/UriKatsirPrivate/snap) under `benchmarks/complexity-tier-benchmark.md` and `benchmarks/banking-intent-classification-benchmark.md`. The service itself is live at [snap-854735162550.us-central1.run.app](https://snap-854735162550.us-central1.run.app) if you want to poke at the Decisions dashboard directly.
