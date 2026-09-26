#!/usr/bin/env python3
"""Benchmark complexity-tier classification -- the actual task JEV/Haiku were
benchmarked on in https://docs.litellm.ai/blog/jev-auto-router-benchmark --
recreated against snap's own selector, for a task-matched comparison instead
of comparing across two different classification jobs.

JEV's tiers, per that post: SIMPLE (basic lookup tasks), MEDIUM (routine
drafting and localized code), COMPLEX (coupled technical work), REASONING
(proofs, optimization, conflicting objectives). Their exact 80 test cases
were never published, so CASES below is authored fresh from those
descriptions -- same task and label set, not the same literal inputs.

Two backends, mirroring scripts/benchmark_focus.py:
- `local`: calls `GeminiSelector.select()` in-process.
- `http`: POSTs to a live `/v1/decisions/route` endpoint, using the tier
  names as route candidate ids (route accepts an arbitrary candidate list,
  so this is a legitimate use of that endpoint, not a repurposing hack).

Usage:
    python scripts/benchmark_tier.py --mode local
    python scripts/benchmark_tier.py --mode http --url https://your-service-url

Requires GOOGLE_CLOUD_PROJECT / ADC set up for --mode local. Both modes make
real, billed Vertex AI calls (cases * repeats).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_config  # noqa: E402
from app.selector import GeminiSelector  # noqa: E402
from _benchmark_common import Backend, Case, report, run, save_result, summarize  # noqa: E402

TIER_IDS = ["SIMPLE", "MEDIUM", "COMPLEX", "REASONING"]

CASES: list[Case] = [
    # SIMPLE -- basic lookup tasks
    Case("simp-01", "What's the HTTP status code for 'not found'?", "SIMPLE"),
    Case("simp-02", "What does the acronym API stand for?", "SIMPLE"),
    Case("simp-03", "What's the default port for HTTPS?", "SIMPLE"),
    Case("simp-04", "What's the capital of France?", "SIMPLE"),
    Case("simp-05", "How many bytes are in a kilobyte?", "SIMPLE"),
    Case("simp-06", "What's the file extension for a Python file?", "SIMPLE"),
    Case("simp-07", "What's the boiling point of water in Celsius?", "SIMPLE"),
    Case("simp-08", "What does CPU stand for?", "SIMPLE"),
    Case("simp-09", "What's the syntax for a Python list comprehension?", "SIMPLE"),
    Case("simp-10", "What command lists files in a directory on Linux?", "SIMPLE"),
    Case("simp-11", "What's the ASCII code for the letter 'A'?", "SIMPLE"),
    Case("simp-12", "What's the plural of 'octopus'?", "SIMPLE"),
    Case("simp-13", "What's the time zone abbreviation for Pacific Standard Time?", "SIMPLE"),
    Case("simp-14", "What does JSON stand for?", "SIMPLE"),
    Case("simp-15", "What's the keyboard shortcut to copy text on Windows?", "SIMPLE"),
    Case("simp-16", "What's the default branch name convention in modern git repos?", "SIMPLE"),
    Case("simp-17", "What's the SI unit for measuring force?", "SIMPLE"),
    Case("simp-18", "What does the acronym SQL stand for?", "SIMPLE"),
    Case("simp-19", "What's the maximum value of a signed 32-bit integer?", "SIMPLE"),
    Case("simp-20", "What's the file extension for a compiled Java class?", "SIMPLE"),
    # MEDIUM -- routine drafting and localized code
    Case("med-01", "Write a function that reverses a string.", "MEDIUM"),
    Case("med-02", "Draft a short email letting the team know the deploy is delayed by an hour.", "MEDIUM"),
    Case("med-03", "Write a regex that matches a US phone number.", "MEDIUM"),
    Case("med-04", "Add a docstring to this function.", "MEDIUM"),
    Case("med-05", "Write a unit test for this addition function.", "MEDIUM"),
    Case("med-06", "Draft a one-paragraph summary of what this PR changes.", "MEDIUM"),
    Case("med-07", "Write a SQL query to select all users created in the last 7 days.", "MEDIUM"),
    Case("med-08", "Add a null check before this dictionary lookup.", "MEDIUM"),
    Case("med-09", "Write a bash one-liner to count lines in a file.", "MEDIUM"),
    Case("med-10", "Draft a commit message for this small bug fix.", "MEDIUM"),
    Case("med-11", "Write a function to check if a number is prime.", "MEDIUM"),
    Case("med-12", "Add type hints to this function's signature.", "MEDIUM"),
    Case("med-13", "Write a short changelog entry for this release.", "MEDIUM"),
    Case("med-14", "Fix the indentation in this code snippet.", "MEDIUM"),
    Case("med-15", "Write a function that converts Celsius to Fahrenheit.", "MEDIUM"),
    Case("med-16", "Draft a Slack message announcing a scheduled maintenance window.", "MEDIUM"),
    Case("med-17", "Write a query to count rows in a table grouped by status.", "MEDIUM"),
    Case("med-18", "Add a try/except around this file read.", "MEDIUM"),
    Case("med-19", "Write a small script to rename all .txt files in a folder to .md.", "MEDIUM"),
    Case("med-20", "Draft a one-line docstring for this class.", "MEDIUM"),
    # COMPLEX -- coupled technical work
    Case("cplx-01", "Migrate the authentication system from session cookies to JWT without breaking existing logged-in users.", "COMPLEX"),
    Case("cplx-02", "Refactor the payment service to support multiple currencies across all downstream consumers.", "COMPLEX"),
    Case("cplx-03", "Redesign the database schema to support multi-tenancy without a full data migration downtime.", "COMPLEX"),
    Case("cplx-04", "Coordinate a rollout of a new caching layer across three services that share the same cache keys.", "COMPLEX"),
    Case("cplx-05", "Untangle the circular dependency between the billing and notifications modules.", "COMPLEX"),
    Case("cplx-06", "Move the monolith's background jobs to a separate queue-based service while keeping exactly-once delivery.", "COMPLEX"),
    Case("cplx-07", "Update the API versioning scheme in a way that doesn't break any of the five existing client SDKs.", "COMPLEX"),
    Case("cplx-08", "Reconcile the two divergent user schemas from the merged codebases into one canonical model.", "COMPLEX"),
    Case("cplx-09", "Design a backward-compatible way to change the primary key type on a table with foreign keys in six other tables.", "COMPLEX"),
    Case("cplx-10", "Coordinate the retry logic across the gateway, the queue, and the downstream service so failures aren't double-processed.", "COMPLEX"),
    Case("cplx-11", "Split the shared database between two services being separated into independent deployables.", "COMPLEX"),
    Case("cplx-12", "Redesign the permission system so it works consistently across the API, the admin UI, and the CLI.", "COMPLEX"),
    Case("cplx-13", "Change the event schema in a way that keeps both old and new consumers working during the transition.", "COMPLEX"),
    Case("cplx-14", "Rework the deployment pipeline so staging and production can run different service versions safely.", "COMPLEX"),
    Case("cplx-15", "Resolve the inconsistency between the cache's TTL and the database's eventual consistency window.", "COMPLEX"),
    Case("cplx-16", "Consolidate three overlapping logging systems into one without losing any existing alerting.", "COMPLEX"),
    Case("cplx-17", "Redesign the rate limiter so it works correctly across multiple regions with independent clocks.", "COMPLEX"),
    Case("cplx-18", "Migrate the search index to a new provider while keeping search results consistent during the cutover.", "COMPLEX"),
    Case("cplx-19", "Restructure the test suite so integration tests don't depend on execution order across modules.", "COMPLEX"),
    Case("cplx-20", "Change the ID generation strategy from auto-increment to UUID across a system with existing external references.", "COMPLEX"),
    # REASONING -- proofs, optimization, conflicting objectives
    Case("reas-01", "Prove that this recursive function always terminates.", "REASONING"),
    Case("reas-02", "Find the algorithm with the best worst-case time complexity for this problem and justify why.", "REASONING"),
    Case("reas-03", "We need this system to be both strongly consistent and available during a network partition -- work out the tradeoff and pick one.", "REASONING"),
    Case("reas-04", "Prove that this sorting algorithm is stable.", "REASONING"),
    Case("reas-05", "Optimize this query's execution plan to minimize both latency and memory usage, which pull in opposite directions here.", "REASONING"),
    Case("reas-06", "Determine whether this concurrent algorithm is free of deadlock under all interleavings.", "REASONING"),
    Case("reas-07", "We want to minimize cost and maximize availability at the same time for this deployment -- find the best tradeoff point.", "REASONING"),
    Case("reas-08", "Prove that this cache invalidation strategy never serves stale data.", "REASONING"),
    Case("reas-09", "Work out the optimal batch size that minimizes total processing time given both per-item and per-batch overhead.", "REASONING"),
    Case("reas-10", "Determine the minimum number of servers needed to guarantee no request is dropped under the worst-case load pattern.", "REASONING"),
    Case("reas-11", "Prove that two given regular expressions match the same language.", "REASONING"),
    Case("reas-12", "We need low latency for reads and strong durability for writes, but the two requirements pull the storage engine choice in opposite directions -- resolve it.", "REASONING"),
    Case("reas-13", "Show that this distributed lock implementation can't have two holders at once.", "REASONING"),
    Case("reas-14", "Find the theoretical lower bound on the number of comparisons needed to sort this input.", "REASONING"),
    Case("reas-15", "Balance the conflicting goals of minimizing bundle size and maximizing runtime performance for this build.", "REASONING"),
    Case("reas-16", "Prove that this hashing scheme has no collisions for the given input domain.", "REASONING"),
    Case("reas-17", "Determine whether this scheduling algorithm can starve a given class of tasks indefinitely.", "REASONING"),
    Case("reas-18", "We want to reduce vendor lock-in but also minimize integration cost -- these pull in opposite directions, find the right balance.", "REASONING"),
    Case("reas-19", "Prove that rolling back this migration is safe even if it's interrupted halfway through.", "REASONING"),
    Case("reas-20", "Optimize this algorithm's memory usage without increasing its time complexity.", "REASONING"),
]


class LocalBackend(Backend):
    """Calls GeminiSelector.select() in-process."""

    def __init__(self):
        config = load_config()
        self.label = f"local (in-process, model={config.gemini_model})"
        self._selector = GeminiSelector(config)

    def call(self, case: Case, tag: str) -> tuple[str | None, bool, float, float | None]:
        started = time.perf_counter()
        result = self._selector.select(TIER_IDS, {"task": case.task})
        latency_ms = (time.perf_counter() - started) * 1000
        return result.choice_id, result.abstained, latency_ms, result.raw.get("cost_usd")


class HttpBackend(Backend):
    """POSTs to a live /v1/decisions/route endpoint, using the tier names as
    route candidate ids -- route accepts any candidate list, so this is a
    legitimate use of the endpoint. Uses the server-reported
    selector_latency_ms so this machine's own network route to the service
    doesn't leak into the number. Writes real decision records to whatever
    backend that service is configured with."""

    def __init__(self, url: str):
        import httpx

        self.label = f"http ({url})"
        self._client = httpx.Client(base_url=url, timeout=30.0)

    def call(self, case: Case, tag: str) -> tuple[str | None, bool, float, float | None]:
        response = self._client.post(
            "/v1/decisions/route",
            json={
                "task_id": f"bench-{case.task_id}-{tag}",
                "candidates": [{"id": tier, "provider": "tier", "model": tier} for tier in TIER_IDS],
                "context": {"task": case.task},
            },
        )
        response.raise_for_status()
        body = response.json()
        predicted = body["chosen"]["id"] if body["chosen"] else None
        abstained = body["decision"] == "abstained"
        return predicted, abstained, body["selector_latency_ms"], body["selector_cost_usd"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=["local", "http", "both"], default="both")
    parser.add_argument("--url", help="Base URL of a live deployment, required for --mode http/both")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "benchmarks" / "results",
        help="Directory to write per-run JSON results to",
    )
    args = parser.parse_args()

    if args.mode in ("http", "both") and not args.url:
        parser.error("--url is required for --mode http/both")

    backends: list[tuple[str, Backend]] = []
    if args.mode in ("local", "both"):
        backends.append(("local", LocalBackend()))
    if args.mode in ("http", "both"):
        backends.append(("http", HttpBackend(args.url)))

    for mode, backend in backends:
        trials = run(backend, CASES, args.repeats, args.seed)
        summary = summarize(trials, len(CASES), TIER_IDS)
        report(summary, backend.label, TIER_IDS)
        path = save_result(trials, backend.label, summary, "tier", mode, args.out_dir)
        print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
