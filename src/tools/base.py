"""
base.py — BaseTool

Every tool in this project inherits from BaseTool.

Three things every tool MUST define:
  name         → unique identifier       e.g. "doctor_search"
  description  → what it does            used by LangGraph to select the tool
  capabilities → what operations it owns e.g. {"search", "find_doctor"}
  execute()    → the only public method  always returns ToolResponse
"""

from abc import ABC, abstractmethod
from src.tools.models import ToolRequest, ToolResponse


class BaseTool(ABC):
    """Abstract base that every tool inherits."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool id. e.g. 'doctor_search', 'appointment'"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One sentence. LangGraph reads this to decide which tool to call."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> set[str]:
        """
        Set of operation strings this tool can handle.
        Registry uses this for capability-based routing.
        e.g. {"search"}  or  {"book", "cancel", "reschedule", "availability"}
        """
        ...

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Only public entry point the agent calls.
        request.operation decides what happens internally.
        Must NEVER raise — always return ToolResponse.
        """
        ...

    def supports(self, operation: str) -> bool:
        """Check if this tool handles the given operation."""
        return operation in self.capabilities

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r} capabilities={self.capabilities}>"
