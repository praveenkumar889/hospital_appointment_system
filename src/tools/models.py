"""
models.py — ToolRequest and ToolResponse

The ONLY objects that travel between the agent and tools.
No raw dicts. No endpoint JSON. Strongly typed.
"""

from typing import Any, Optional
from pydantic import BaseModel


class ToolRequest(BaseModel):
    """
    Input to every tool. Minimal — only what the tool needs.

    operation : what to do         e.g. "search", "book", "cancel"
    payload   : all data the tool  e.g. {"q": "heart specialist", "client_id": "glh-chn"}
                needs including any tenant/branch info as business data
    """
    operation: str
    payload:   dict[str, Any] = {}


class ToolResponse(BaseModel):
    """
    Output from every tool. Always the same shape.
    LangGraph reads only this — never raw API JSON.

    success  : True / False
    data     : the actual result (doctors list, appointment dict, slots…)
    message  : human-readable summary for the agent reply
    error    : machine-readable error detail when success=False
    metadata : extras — intent, booking_links, appointment_id, totals, etc.
    """
    success:  bool
    data:     Any               = None
    message:  str               = ""
    error:    Optional[str]     = None
    metadata: dict[str, Any]    = {}

    @classmethod
    def ok(cls, data: Any, message: str = "", metadata: dict[str, Any] = {}) -> "ToolResponse":
        """Shortcut — successful response."""
        return cls(success=True, data=data, message=message, metadata=metadata)

    @classmethod
    def fail(cls, error: str, message: str = "", metadata: dict[str, Any] = {}) -> "ToolResponse":
        """Shortcut — failed response."""
        return cls(success=False, data=None, error=error, message=message or error, metadata=metadata)
