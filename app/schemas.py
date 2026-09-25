import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

FocusId = Literal["inspect", "implement", "verify", "answer"]
RouteDecisionKind = Literal["pinned", "selected", "fallback", "abstained"]
FocusDecisionKind = Literal["selected", "fallback"]


class RouteCandidate(BaseModel):
    id: str
    provider: str
    model: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RouteDecisionRequest(BaseModel):
    task_id: str
    candidates: list[RouteCandidate]
    pinned_route_id: str | None = None
    fallback_route_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class RouteDecisionResponse(BaseModel):
    task_id: str
    decision: RouteDecisionKind
    chosen: RouteCandidate | None
    fallback_used: bool
    record_id: str
    selector_latency_ms: float | None = None


class ToolDef(BaseModel):
    name: str
    description: str = ""


class FocusDecisionRequest(BaseModel):
    task_id: str
    session_id: str
    available_tools: list[ToolDef] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class FocusDecisionResponse(BaseModel):
    task_id: str
    session_id: str
    decision: FocusDecisionKind
    focus: FocusId
    tools: list[str]
    fallback_used: bool
    record_id: str
    selector_latency_ms: float | None = None


class SelectionResult(BaseModel):
    choice_id: str | None
    abstained: bool
    raw: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal["route", "focus"]
    task_id: str
    offered: list[str]
    selector_choice: str | None
    abstained: bool
    validated: bool
    fallback_used: bool
    final_choice: str | None
    selector_latency_ms: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecuteRequest(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ExecuteResponse(BaseModel):
    tool_name: str
    status: Literal["ok", "rejected"]
    output: str
