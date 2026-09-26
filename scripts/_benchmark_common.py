"""Shared harness for snap's authored-cases classification benchmarks.

Both scripts/benchmark_focus.py and scripts/benchmark_tier.py follow the same
shape as https://docs.litellm.ai/blog/jev-auto-router-benchmark: a fixed set
of authored cases with an expected label, repeated N times with a seeded
per-repeat shuffle, scored on match-rate/latency/cost. This module holds the
part that doesn't depend on which label set or backend is being tested.
"""
import json
import random
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Case:
    task_id: str
    task: str
    expected: str


@dataclass
class Trial:
    case: Case
    predicted: str | None
    abstained: bool
    latency_ms: float
    cost_usd: float | None

    @property
    def correct(self) -> bool:
        return self.predicted == self.case.expected


class Backend(ABC):
    """One call = one classification decision for a case. Returns
    (predicted, abstained, latency_ms, cost_usd)."""

    label: str

    @abstractmethod
    def call(self, case: Case, tag: str) -> tuple[str | None, bool, float, float | None]: ...


def run(backend: Backend, cases: list[Case], repeats: int, seed: int) -> list[Trial]:
    trials: list[Trial] = []
    for repeat in range(repeats):
        order = cases.copy()
        random.Random(seed + repeat).shuffle(order)
        for i, case in enumerate(order, 1):
            predicted, abstained, latency_ms, cost_usd = backend.call(case, tag=f"r{repeat}")
            trials.append(
                Trial(case=case, predicted=predicted, abstained=abstained, latency_ms=latency_ms, cost_usd=cost_usd)
            )
            print(
                f"[repeat {repeat + 1}/{repeats} {i}/{len(order)}] "
                f"{case.task_id}: expected={case.expected} got={predicted or 'ABSTAIN'} "
                f"{'OK' if predicted == case.expected else 'MISS'}"
            )
    return trials


def summarize(trials: list[Trial], num_cases: int, labels: list[str]) -> dict:
    n = len(trials)
    correct = sum(t.correct for t in trials)
    latencies = [t.latency_ms for t in trials]
    costs = [t.cost_usd for t in trials if t.cost_usd is not None]

    per_label = {}
    for label in labels:
        label_trials = [t for t in trials if t.case.expected == label]
        per_label[label] = {"correct": sum(t.correct for t in label_trials), "total": len(label_trials)}

    confusion = {}
    for expected in labels:
        row = [t for t in trials if t.case.expected == expected]
        confusion[expected] = {p: sum(1 for t in row if t.predicted == p and not t.abstained) for p in labels}
        confusion[expected]["abstain"] = sum(1 for t in row if t.abstained)

    return {
        "cases": num_cases,
        "repeats": n // num_cases,
        "total_calls": n,
        "correct": correct,
        "match_rate": correct / n,
        "abstained": sum(t.abstained for t in trials),
        "per_label": per_label,
        "confusion_matrix": confusion,
        "latency_ms": {
            "median": statistics.median(latencies),
            "p95": statistics.quantiles(latencies, n=20)[18],
            "min": min(latencies),
            "max": max(latencies),
        },
        "cost_usd": {"total": sum(costs), "priced_calls": len(costs)} if costs else None,
    }


def report(summary: dict, backend_label: str, labels: list[str]) -> None:
    print("\n=== Classification benchmark ===")
    print(f"backend: {backend_label}")
    print(f"cases: {summary['cases']}, repeats: {summary['repeats']}, total calls: {summary['total_calls']}")
    n = summary["total_calls"]
    print(f"\nOverall match rate: {summary['correct']}/{n} ({100 * summary['match_rate']:.2f}%)")
    print(f"Abstained: {summary['abstained']}/{n} ({100 * summary['abstained'] / n:.2f}%)")

    print("\nPer-label match rate:")
    for label, counts in summary["per_label"].items():
        print(f"  {label:10s} {counts['correct']}/{counts['total']} ({100 * counts['correct'] / counts['total']:.2f}%)")

    print("\nConfusion matrix (rows=expected, cols=predicted, 'X'=abstain):")
    header = "".join(f"{p:>10s}" for p in [*labels, "abstain"])
    print(f"{'':10s}{header}")
    for expected, row in summary["confusion_matrix"].items():
        counts = [row[p] for p in labels] + [row["abstain"]]
        print(f"{expected:10s}" + "".join(f"{c:>10d}" for c in counts))

    lat = summary["latency_ms"]
    print("\nLatency (ms):")
    print(f"  median: {lat['median']:.2f}")
    print(f"  p95:    {lat['p95']:.2f}")
    print(f"  min/max: {lat['min']:.2f} / {lat['max']:.2f}")

    cost = summary["cost_usd"]
    if cost:
        print(f"\nCost: ${cost['total']:.4f} total over {cost['priced_calls']} priced calls (${cost['total'] / cost['priced_calls'] * 1000:.4f}/1000 calls)")
    else:
        print("\nCost: unpriced (model not in GeminiSelector._PRICE_PER_MILLION_TOKENS_USD)")


def save_result(trials: list[Trial], backend_label: str, summary: dict, name: str, mode: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{name}_{mode}_{timestamp}.json"
    payload = {
        "name": name,
        "backend": backend_label,
        "mode": mode,
        "recorded_at": timestamp,
        "summary": summary,
        "trials": [
            {
                "task_id": t.case.task_id,
                "task": t.case.task,
                "expected": t.case.expected,
                "predicted": t.predicted,
                "abstained": t.abstained,
                "correct": t.correct,
                "latency_ms": t.latency_ms,
                "cost_usd": t.cost_usd,
            }
            for t in trials
        ],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path
