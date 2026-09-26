import logging
import secrets
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from app.config import Config, load_config
from app.focus import decide_focus
from app.records import DecisionRecorder, get_recorder
from app.routing import decide_route
from app.schemas import (
    DecisionRecord,
    ExecuteRequest,
    ExecuteResponse,
    FocusDecisionRequest,
    FocusDecisionResponse,
    RouteDecisionRequest,
    RouteDecisionResponse,
)
from app.selector import GeminiSelector, Selector
from app.tools import TOOL_BUNDLES, MockToolExecutor, ToolExecutor

logger = logging.getLogger(__name__)


@lru_cache
def get_config() -> Config:
    return load_config()


@lru_cache
def get_selector() -> Selector:
    return GeminiSelector(get_config())


@lru_cache
def get_decision_recorder() -> DecisionRecorder:
    return get_recorder(get_config())


@lru_cache
def get_tool_executor() -> ToolExecutor:
    return MockToolExecutor()


def require_admin_key(
    x_admin_key: str | None = Header(default=None),
    config: Config = Depends(get_config),
) -> None:
    """Guards destructive endpoints. Fails closed: with no ADMIN_API_KEY set,
    the endpoint is unusable rather than silently open to anyone."""
    if not config.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, config.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key header")


def warm_up_selector() -> None:
    """Pay the first call's TLS handshake and ADC token fetch once at
    startup, so it doesn't land on whichever request happens to be first."""
    config = get_config()
    if not config.gcp_project:
        return
    try:
        get_selector().select(["warmup"], {})
    except Exception:
        logger.warning("Selector warm-up call failed; continuing anyway", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warm_up_selector()
    yield


app = FastAPI(
    title="snap",
    description="Decision layer for a coding harness, backed by Gemini.",
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/decisions/route", response_model=RouteDecisionResponse)
def route_decision(
    request: RouteDecisionRequest,
    background_tasks: BackgroundTasks,
    selector: Selector = Depends(get_selector),
    recorder: DecisionRecorder = Depends(get_decision_recorder),
) -> RouteDecisionResponse:
    response, record = decide_route(request, selector)
    # Recording happens after the response is sent, so the recorder's
    # latency never adds to the decision itself.
    background_tasks.add_task(recorder.record, record)
    return response


@app.post("/v1/decisions/focus", response_model=FocusDecisionResponse)
def focus_decision(
    request: FocusDecisionRequest,
    background_tasks: BackgroundTasks,
    selector: Selector = Depends(get_selector),
    recorder: DecisionRecorder = Depends(get_decision_recorder),
) -> FocusDecisionResponse:
    response, record = decide_focus(request, selector)
    background_tasks.add_task(recorder.record, record)
    return response


@app.post("/v1/execute", response_model=ExecuteResponse)
def execute(
    request: ExecuteRequest,
    executor: ToolExecutor = Depends(get_tool_executor),
) -> ExecuteResponse:
    allowed = {tool for bundle in TOOL_BUNDLES.values() for tool in bundle}
    if request.tool_name not in allowed:
        return ExecuteResponse(tool_name=request.tool_name, status="rejected", output="tool not in any known bundle")
    result = executor.execute(request.tool_name, request.args)
    return ExecuteResponse(tool_name=request.tool_name, status="ok", output=result["output"])


@app.get("/v1/decisions/recent", response_model=list[DecisionRecord])
def recent_decisions(
    limit: int = 25,
    recorder: DecisionRecorder = Depends(get_decision_recorder),
) -> list[DecisionRecord]:
    return recorder.recent(limit)


@app.delete("/v1/decisions", dependencies=[Depends(require_admin_key)])
def clear_decisions(
    task_id: list[str] | None = None,
    recorder: DecisionRecorder = Depends(get_decision_recorder),
) -> dict[str, str]:
    recorder.clear(task_id)
    return {"status": "cleared"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
