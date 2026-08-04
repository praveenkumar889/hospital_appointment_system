"""
state.py — AgentState

The heart of the agent. Every node reads from and writes to this.

AgentState
├── messages          (LangGraph message list with auto-merge)
├── conversation      (intent, last message, last response)
├── workflow          (business data — what the user is doing)
├── memory            (long-term user preferences & history from MongoDB)
├── tool              (tool results only)
├── runtime           (execution data — what the system is doing)
├── session_id        (thread ID for current conversation)
├── user_id           (patient phone number / WhatsApp / patient ID)
└── tenant_id         (hospital tenant ID e.g. "glh-chn")
"""

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class ConversationState(TypedDict):
    intent:            str     # BOOK_APPOINTMENT | SEARCH_DOCTOR | MANAGE_APPOINTMENT | GENERAL_QUERY
    last_user_message: str
    last_response:     str


class WorkflowState(TypedDict):
    """
    Business data only. No execution logic.
    Works for any workflow — booking, labs, insurance.
    """
    workflow_type: str     # "booking" | "lab" | "insurance"
    data:          dict    # dynamic fields — each workflow puts its own keys here
    status:        str     # pending | confirmed | cancelled | rescheduled


class MemoryState(TypedDict):
    preferences:     dict   # {"preferred_city": "Chennai", "preferred_language": "Tamil"}
    booking_history: list   # past conversation workflow summaries from MongoDB
    summary:         str    # LLM-generated overall patient summary across interactions


class ToolState(TypedDict):
    """Tool results only. No execution logic."""
    doctor_results: list            # results from doctor search
    availability:   list            # available time slots
    tool_output:    Optional[dict]  # {"data": ..., "message": ..., "error": ...}
    tool_success:   bool
    last_tool:      Optional[str]   # last operation executed


class RuntimeState(TypedDict):
    """
    Execution data — what the SYSTEM is doing right now.
    Separate from workflow (business) data for clean debugging.
    """
    next_action: Optional[str]  # "search" | "book" | "cancel" | "ask_user"
    needs_info:  list           # fields still required from user
    retry_count: int
    errors:      list           # list of error strings from this run


class AgentState(TypedDict):
    messages:     Annotated[list, add_messages]
    conversation: ConversationState
    workflow:     WorkflowState
    memory:       MemoryState
    tool:         ToolState
    runtime:      RuntimeState
    session_id:   str
    user_id:      str
    tenant_id:    str
