"""
decision node — Workflow Decision Engine

Decides WHAT ACTION is needed next based on current state.
Intent = what the user wants (high-level).
Decision = what step the system needs now (specific).

Data-driven: reads from DECISION_MAP in rules.py.
Pure Python. No LLM.
"""

import logging
from src.agent.state import AgentState
from src.agent.rules import DECISION_MAP

logger = logging.getLogger("agent_nodes")


def workflow_decision(state: AgentState) -> dict:
    """Decide next_action based on intent, workflow data, and runtime."""
    intent = state["conversation"]["intent"]
    data   = state["workflow"]["data"]
    needs  = state["runtime"].get("needs_info", [])
    rules  = DECISION_MAP.get(intent, {})

    has_doctor = bool(data.get("doctor_id") or data.get("doctor_name"))

    # Dynamic Rule: If location/city is missing from state -> ask user first!
    if "city" in needs:
        return _set_action(state, "ask_user")

    # Intent 1: SEARCH_DOCTOR -> search
    if intent == "SEARCH_DOCTOR":
        return _set_action(state, rules.get("default", "search"))

    # Intent 2: BOOK_APPOINTMENT
    if intent == "BOOK_APPOINTMENT":
        if not has_doctor:
            return _set_action(state, rules.get("no_doctor", "search"))
        if "time" in needs or not data.get("time"):
            return _set_action(state, "search")
        if needs:
            return _set_action(state, "ask_user")
        return _set_action(state, rules.get("ready", "book"))

    # Intent 3: CANCEL_APPOINTMENT
    if intent == "CANCEL_APPOINTMENT":
        if needs:
            return _set_action(state, "ask_user")
        return _set_action(state, rules.get("default", "cancel"))

    # Intent 4: RESCHEDULE_APPOINTMENT
    if intent == "RESCHEDULE_APPOINTMENT":
        if "time" in needs or not data.get("time"):
            return _set_action(state, "search")
        if needs:
            return _set_action(state, "ask_user")
        return _set_action(state, rules.get("default", "reschedule"))

    # Generic fallback: if needs is not empty → ask user
    if needs:
        return _set_action(state, "ask_user")

    return _set_action(state, "ask_user")


def _set_action(state: AgentState, action: str) -> dict:
    """Helper — set next_action in runtime state."""
    logger.info(f"  [NODE 6: DECISION_ENGINE] Intent: '{state['conversation']['intent']}' -> Action Decided: '{action}'")
    return {"runtime": {**state["runtime"], "next_action": action}}
