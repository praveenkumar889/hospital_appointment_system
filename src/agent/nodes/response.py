"""
response node — Generate the final reply using LLM.
Passes full state (workflow_data, search_results, memory, needs_info) to response prompt.
Includes clean deterministic formatting for successful reschedule and cancel transactions on the current turn.
"""

import logging
from langchain_core.messages import HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.nodes._shared import llm, prompts

logger = logging.getLogger("agent_nodes")


def generate_response(state: AgentState) -> dict:
    """Generate human-readable reply from current state using LLM."""
    intent = state["conversation"]["intent"]
    runtime_state = state.get("runtime", {})
    next_action = runtime_state.get("next_action")
    tool_state = state.get("tool", {})
    tool_output = tool_state.get("tool_output", {})
    tool_success = tool_state.get("tool_success", False)

    logger.info(f"  [NODE 9: DEBUG] intent='{intent}' | next_action='{next_action}' | tool_success={tool_success}")

    # Clean deterministic response ONLY if a transaction (reschedule/cancel) was executed ON THIS TURN!
    if next_action in ["reschedule", "cancel"] and tool_success and isinstance(tool_output, dict):
        data = tool_output.get("data", {})
        appt_id = data.get("appointment_id") or state["workflow"]["data"].get("appointment_id", "your appointment")
        
        if next_action == "reschedule" or data.get("status") == "rescheduled":
            new_date = data.get("new_date") or state["workflow"]["data"].get("date") or "requested date"
            new_time = data.get("new_time") or state["workflow"]["data"].get("time") or "requested time"
            reply = (
                f"Your appointment ({appt_id}) has been successfully rescheduled to {new_date} at {new_time}.\n\n"
                f"Thank you for choosing Gleneagles Hospitals!"
            )
            logger.info(f"  [NODE 9: GENERATE_RESPONSE] Formatted Clean Reschedule Reply for {appt_id}")
            return {
                "messages":     [AIMessage(content=reply)],
                "conversation": {**state["conversation"], "last_response": reply},
            }

        if next_action == "cancel" or data.get("status") == "cancelled":
            reply = (
                f"Your appointment ({appt_id}) has been successfully cancelled.\n\n"
                f"If you need to book a new appointment in the future, please feel free to reach out!"
            )
            logger.info(f"  [NODE 9: GENERATE_RESPONSE] Formatted Clean Cancel Reply for {appt_id}")
            return {
                "messages":     [AIMessage(content=reply)],
                "conversation": {**state["conversation"], "last_response": reply},
            }

    # Standard LLM response generation for inquiries, general chat, search results, and questions
    recent = "\n".join(f"{m.type}: {m.content}" for m in state["messages"][-4:])

    prompt = prompts.get(
        "response",
        tenant_id=state["tenant_id"],
        intent=state["conversation"]["intent"],
        workflow_data=state["workflow"]["data"],
        search_results=state["runtime"].get("search_results", []),
        tool_output=state["tool"]["tool_output"],
        memory_summary=state["memory"]["summary"],
        needs_info=state["runtime"].get("needs_info", []),
        messages=recent,
    )

    reply_raw = llm.invoke([HumanMessage(content=prompt)])
    reply_text = reply_raw.content if hasattr(reply_raw, "content") else str(reply_raw)
    
    # Deterministic Spacing Normalizer: Enforce exact single-line breaks inside cards & 1 blank line between cards
    import re
    cleaned_reply = reply_text.replace("\r\n", "\n")
    
    # 1. Ensure SINGLE line break (\n) inside entire doctor block (Name -> Department -> Branch -> Slots -> Morning -> Afternoon)
    cleaned_reply = re.sub(r'(\*\*[^\n]+\*\*)\n\s*\n+(Department:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Department:[^\n]*)\n\s*\n+(Branch:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Branch:[^\n]*)\n\s*\n+(📅 Available Time Slots)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(📅 Available Time Slots[^\n]*)\n\s*\n+(Morning:|Afternoon:|Evening:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Morning:[^\n]*)\n\s*\n+(Afternoon:|Evening:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Afternoon:[^\n]*)\n\s*\n+(Evening:)', r'\1\n\2', cleaned_reply)

    # 2. Collapse any 3+ newlines to max 2 newlines (\n\n) for card separation
    cleaned_reply = re.sub(r'\n{3,}', '\n\n', cleaned_reply).strip()

    logger.info(f"  [NODE 9: GENERATE_RESPONSE] Generated Cleaned Reply: '{cleaned_reply[:100]}...'")
    return {
        "messages":     [AIMessage(content=cleaned_reply)],
        "conversation": {**state["conversation"], "last_response": cleaned_reply},
    }
