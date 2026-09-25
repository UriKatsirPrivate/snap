from abc import ABC, abstractmethod
from typing import Any

from app.schemas import FocusId

# Host-defined tool bundle per focus. The selector only ever returns a focus
# id; it never names a tool directly.
TOOL_BUNDLES: dict[FocusId, list[str]] = {
    "inspect": ["read_file", "list_dir", "grep"],
    "implement": ["read_file", "write_file", "grep"],
    "verify": ["run_tests", "read_file"],
    "answer": [],
}


class ToolExecutor(ABC):
    @abstractmethod
    def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]: ...


class MockToolExecutor(ToolExecutor):
    """Stands in for a real coding-agent tool backend. Returns fake results
    so the decision layer, validation, and logging can be exercised end to
    end before a real executor is wired in."""

    def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": tool_name,
            "status": "ok",
            "output": f"mock result for '{tool_name}' with args={args}",
        }
