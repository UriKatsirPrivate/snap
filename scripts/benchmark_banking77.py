#!/usr/bin/env python3
"""Benchmark banking-intent classification -- the task Jev/Terra/Luna were
benchmarked on in
https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/
-- recreated against snap's own selector, for a task-matched comparison.

That article's benchmark uses PolyAI's banking77 dataset (public, CC BY 4.0,
https://github.com/PolyAI-LDN/task-specific-datasets): real customer-support
utterances labeled with one of 77 banking intents. A local snapshot of its
test split is committed at benchmarks/data/banking77_test.csv (fetched from
that repo's banking_data/test.csv) so this script doesn't need network
access to the dataset at run time -- only to Vertex AI / the deployed
service to classify.

Note: the article's own accuracy/latency/cost numbers for Jev/Terra/Luna are
cited from that page, not reproduced here -- only the task and dataset are
recreated, against `app/selector.py:GeminiSelector`.

Unlike scripts/benchmark_tier.py's small authored dataset, banking77's test
split has 3080 examples across 77 classes (40 each) -- running the full set
is expensive at 77-way classification, so this samples N examples per class
(stratified, seeded) instead of the full set or repeated passes.

Two backends, mirroring scripts/benchmark_tier.py:
- `local`: calls `GeminiSelector.select()` in-process, with the 77 intent
  names as the option list.
- `http`: POSTs to a live `/v1/decisions/route` endpoint, using the 77
  intent names as route candidate ids.

Usage:
    python scripts/benchmark_banking77.py --mode local
    python scripts/benchmark_banking77.py --mode http --url https://your-service-url

Requires GOOGLE_CLOUD_PROJECT / ADC set up for --mode local. Both modes make
real, billed Vertex AI calls (sample_per_class * 77 * repeats).
"""
import argparse
import csv
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_config  # noqa: E402
from app.selector import GeminiSelector  # noqa: E402
from _benchmark_common import Backend, Case, report, run, save_result, summarize  # noqa: E402

DATA_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "data" / "banking77_test.csv"


def load_categories(path: Path = DATA_PATH) -> list[str]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    return sorted({row["category"] for row in rows})


def load_cases(sample_per_class: int, seed: int, categories: list[str], path: Path = DATA_PATH) -> list[Case]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    by_category: dict[str, list[str]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row["text"])

    allowed = set(categories)
    rng = random.Random(seed)
    cases: list[Case] = []
    for category, texts in sorted(by_category.items()):
        if category not in allowed:
            continue
        sample = rng.sample(texts, min(sample_per_class, len(texts)))
        for i, text in enumerate(sample, 1):
            cases.append(Case(f"{category}-{i:02d}", text, category))
    return cases


class LocalBackend(Backend):
    """Calls GeminiSelector.select() in-process with the 77 intents as options."""

    def __init__(self, categories: list[str]):
        config = load_config()
        self.label = f"local (in-process, model={config.gemini_model})"
        self._categories = categories
        self._selector = GeminiSelector(config)

    def call(self, case: Case, tag: str) -> tuple[str | None, bool, float, float | None]:
        started = time.perf_counter()
        result = self._selector.select(self._categories, {"utterance": case.task})
        latency_ms = (time.perf_counter() - started) * 1000
        return result.choice_id, result.abstained, latency_ms, result.raw.get("cost_usd")


class HttpBackend(Backend):
    """POSTs to a live /v1/decisions/route endpoint, using the 77 intent
    names as route candidate ids. Uses the server-reported
    selector_latency_ms so this machine's own network route to the service
    doesn't leak into the number. Writes real decision records to whatever
    backend that service is configured with."""

    def __init__(self, url: str, categories: list[str]):
        import httpx

        self.label = f"http ({url})"
        self._categories = categories
        self._client = httpx.Client(base_url=url, timeout=30.0)

    def call(self, case: Case, tag: str) -> tuple[str | None, bool, float, float | None]:
        response = self._client.post(
            "/v1/decisions/route",
            json={
                "task_id": f"bench-{case.task_id}-{tag}",
                "candidates": [{"id": c, "provider": "intent", "model": c} for c in self._categories],
                "context": {"utterance": case.task},
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
    parser.add_argument("--sample-per-class", type=int, default=7)
    parser.add_argument(
        "--max-classes",
        type=int,
        default=50,
        help=(
            "Cap on the number of intent classes to include as selector options. "
            "GeminiSelector's constrained-enum schema (app/selector.py) rejects "
            "requests above ~53-54 options for this dataset's category names with "
            "a 400 'too much branching for serving' error -- 50 is a safe margin "
            "under that ceiling, not the true max."
        ),
    )
    parser.add_argument("--repeats", type=int, default=1)
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

    categories = load_categories()[: args.max_classes]
    cases = load_cases(args.sample_per_class, args.seed, categories)

    backends: list[tuple[str, Backend]] = []
    if args.mode in ("local", "both"):
        backends.append(("local", LocalBackend(categories)))
    if args.mode in ("http", "both"):
        backends.append(("http", HttpBackend(args.url, categories)))

    for mode, backend in backends:
        trials = run(backend, cases, args.repeats, args.seed)
        summary = summarize(trials, len(cases), categories)
        report(summary, backend.label, categories)
        path = save_result(trials, backend.label, summary, "banking77", mode, args.out_dir)
        print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
