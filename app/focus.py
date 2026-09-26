import time
from typing import get_args

from app.schemas import DecisionRecord, FocusDecisionRequest, FocusDecisionResponse, FocusId
from app.selector import Selector
from app.tools import TOOL_BUNDLES

FOCUS_IDS: list[str] = list(get_args(FocusId))
DEFAULT_FALLBACK_FOCUS: FocusId = "inspect"


def decide_focus(
    request: FocusDecisionRequest,
    selector: Selector,
) -> tuple[FocusDecisionResponse, DecisionRecord]:
    """Pure decision, mirrors decide_route: returns the response alongside
    a record to persist, without performing the write itself."""
    started = time.perf_counter()
    result = selector.select(FOCUS_IDS, request.context)
    latency_ms = (time.perf_counter() - started) * 1000
    cost_usd = result.raw.get("cost_usd")

    validated = (not result.abstained) and result.choice_id in FOCUS_IDS
    fallback_used = not validated
    focus: FocusId = result.choice_id if validated else DEFAULT_FALLBACK_FOCUS  # type: ignore[assignment]

    # Filter the focus's tool bundle against tools the host currently knows
    # to exist, so a stale or renamed tool never gets dispatched.
    available = {t.name for t in request.available_tools} if request.available_tools is not None else None
    bundle = TOOL_BUNDLES[focus]
    tools = [t for t in bundle if available is None or t in available]

    record = DecisionRecord(
        kind="focus",
        task_id=request.task_id,
        offered=FOCUS_IDS,
        selector_choice=result.choice_id,
        abstained=result.abstained,
        validated=validated,
        fallback_used=fallback_used,
        final_choice=focus,
        selector_latency_ms=latency_ms,
        selector_cost_usd=cost_usd,
    )
    return (
        FocusDecisionResponse(
            task_id=request.task_id,
            session_id=request.session_id,
            decision="fallback" if fallback_used else "selected",
            focus=focus,
            tools=tools,
            fallback_used=fallback_used,
            record_id=record.id,
            selector_latency_ms=latency_ms,
            selector_cost_usd=cost_usd,
        ),
        record,
    )
