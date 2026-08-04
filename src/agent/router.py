"""
router.py — Routing Decisions

Pure Python. No LLM. No imports from nodes.
Reads from runtime state for execution decisions.
"""

from src.agent.state import AgentState

_WORKFLOW_INTENTS = {"BOOK_APPOINTMENT", "SEARCH_DOCTOR", "MANAGE_APPOINTMENT",
                     "RESCHEDULE_APPOINTMENT", "CANCEL_APPOINTMENT", "VIEW_APPOINTMENT"}


def after_intent(state: AgentState) -> str:
    """After intent. GENERAL_QUERY → respond. Others → extract entities."""
    if state["conversation"]["intent"] not in _WORKFLOW_INTENTS:
        return "generate_response"
    return "extract_entities"


def after_validation(state: AgentState) -> str:
    """After validation. Always go to workflow decision."""
    return "workflow_decision"


def after_decision(state: AgentState) -> str:
    """After decision. ask_user → respond. Anything else → execute tool."""
    action = state["runtime"].get("next_action", "ask_user")
    if action == "ask_user":
        return "generate_response"
    return "execute_tool"


def after_tool(state: AgentState) -> str:
    """After tool. Successful non-search → save memory. Otherwise → respond."""
    intent  = state["conversation"]["intent"]
    success = state["tool"]["tool_success"]

    if intent != "SEARCH_DOCTOR" and success:
        return "save_memory"
    return "generate_response"
