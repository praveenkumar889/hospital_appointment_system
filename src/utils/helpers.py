"""
helpers.py — Shared Utilities

Small, pure Python helpers used across the project.
No imports from agent/, llm/, or tools/ — keeps this dependency-free.
"""

from typing import Any, Optional
from langchain_core.messages import HumanMessage


def clean_dict(data: dict) -> dict:
    """Remove keys with None or empty-string values from a dict."""
    return {k: v for k, v in data.items() if v is not None and v != ""}


def safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Navigate nested dicts safely without KeyError."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def build_initial_state(
    session_id: str, tenant_id: str, message: str, user_id: Optional[str] = None
) -> dict:
    """
    Build the starting AgentState for an incoming message.
    Called by app.py before invoking the graph.
    """
    return {
        "messages": [HumanMessage(content=message)],
        "conversation": {
            "intent":            "GENERAL_QUERY",
            "last_user_message": message,
            "last_response":     "",
        },
        "workflow": {
            "workflow_type": "booking",     # default — can be overridden per tenant
            "data":          {},            # empty — schema-less entity extraction fills this over turns
            "status":        "pending",
        },
        "memory": {
            "preferences": {}, "booking_history": [], "summary": "",
        },
        "tool": {
            "doctor_results": [], "availability": [],
            "tool_output": None, "tool_success": False,
            "last_tool": None,
        },
        "runtime": {
            "next_action": None,
            "needs_info":  [],
            "retry_count": 0,
            "errors":      [],
        },
        "session_id": session_id,
        "user_id":    user_id or session_id,  # phone number, WhatsApp ID, or session fallback
        "tenant_id":  tenant_id,
    }


def format_doctor_list(doctors: list) -> str:
    """Format a list of doctor dicts into a readable string for prompts."""
    if not doctors:
        return "No doctors found."
    lines = []
    for i, doc in enumerate(doctors, 1):
        name = doc.get("name", "Unknown")
        spec = doc.get("specialization", "")
        lang = doc.get("languages", "")
        lines.append(f"{i}. {name} — {spec}" + (f" ({lang})" if lang else ""))
    return "\n".join(lines)
