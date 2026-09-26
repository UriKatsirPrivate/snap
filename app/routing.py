import time

from app.schemas import DecisionRecord, RouteCandidate, RouteDecisionRequest, RouteDecisionResponse
from app.selector import Selector


def decide_route(
    request: RouteDecisionRequest,
    selector: Selector,
) -> tuple[RouteDecisionResponse, DecisionRecord]:
    """Pure decision: makes the choice and returns it alongside a record to
    persist. Does not perform I/O itself, so the response is never held up
    by a recorder write (see app/api.py, which schedules that in the
    background after the response is sent)."""
    by_id: dict[str, RouteCandidate] = {c.id: c for c in request.candidates}

    # A pinned route bypasses the selector entirely: user intent wins.
    if request.pinned_route_id is not None:
        chosen = by_id.get(request.pinned_route_id)
        record = DecisionRecord(
            kind="route",
            task_id=request.task_id,
            offered=list(by_id.keys()),
            selector_choice=None,
            abstained=False,
            validated=chosen is not None,
            fallback_used=False,
            final_choice=chosen.id if chosen else None,
        )
        return (
            RouteDecisionResponse(
                task_id=request.task_id,
                decision="pinned",
                chosen=chosen,
                fallback_used=False,
                record_id=record.id,
            ),
            record,
        )

    started = time.perf_counter()
    result = selector.select(list(by_id.keys()), request.context)
    latency_ms = (time.perf_counter() - started) * 1000
    cost_usd = result.raw.get("cost_usd")

    # Re-validate: the selector's choice must still be one of the candidates
    # the host actually offered.
    validated = (not result.abstained) and result.choice_id in by_id

    if validated:
        chosen = by_id[result.choice_id]
        decision = "selected"
        fallback_used = False
    else:
        fallback = by_id.get(request.fallback_route_id) if request.fallback_route_id else None
        chosen = fallback
        fallback_used = fallback is not None
        decision = "fallback" if fallback_used else "abstained"

    record = DecisionRecord(
        kind="route",
        task_id=request.task_id,
        offered=list(by_id.keys()),
        selector_choice=result.choice_id,
        abstained=result.abstained,
        validated=validated,
        fallback_used=fallback_used,
        final_choice=chosen.id if chosen else None,
        selector_latency_ms=latency_ms,
        selector_cost_usd=cost_usd,
    )
    return (
        RouteDecisionResponse(
            task_id=request.task_id,
            decision=decision,
            chosen=chosen,
            fallback_used=fallback_used,
            record_id=record.id,
            selector_latency_ms=latency_ms,
            selector_cost_usd=cost_usd,
        ),
        record,
    )
