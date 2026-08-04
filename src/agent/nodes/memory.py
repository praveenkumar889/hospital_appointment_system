"""
memory node — Load and save long-term user memory & conversation summaries.
MemoryService handles persistence. Summarization happens here via LLM.
"""

import logging
from langchain_core.messages import HumanMessage
from src.agent.state import AgentState
from src.agent.nodes._shared import llm, memory, prompts

logger = logging.getLogger("agent_nodes")


def load_memory(state: AgentState) -> dict:
    """Load patient profile & recent conversation summaries from MongoDB using user_id + tenant_id."""
    mem_data = memory.load(user_id=state["user_id"], tenant_id=state["tenant_id"])
    logger.info(f"  [NODE 1: LOAD_MEMORY] Loaded profile for user: {state['user_id']} | Prefs: {mem_data.get('preferences')}")
    return {"memory": mem_data}


def save_memory(state: AgentState) -> dict:
    """Persist conversation summary and update overall user profile memory."""
    wf = state["workflow"]
    session_id = state["session_id"]
    user_id    = state["user_id"]
    tenant_id  = state["tenant_id"]
    data       = wf["data"]

    # 1. Summarize and persist this specific completed workflow/conversation
    conv_prompt = f"Summarize this completed {wf['workflow_type']} interaction briefly: {data}"
    workflow_summary = llm.invoke([HumanMessage(content=conv_prompt)])

    memory.save_conversation_summary(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workflow_type=wf["workflow_type"],
        summary=workflow_summary,
        data=data,
    )

    # 2. Update patient preferences dynamically from completed workflow data
    current_prefs = {**state["memory"].get("preferences", {})}
    for pref_key in ["city", "client_id", "branch", "department", "doctor", "doctor_name", "language"]:
        if data.get(pref_key):
            current_prefs[f"preferred_{pref_key}"] = data[pref_key]

    # 3. Update overall patient profile summary across history
    history = state["memory"].get("booking_history", []) + [{"summary": workflow_summary, "data": data}]
    prompt = prompts.get(
        "memory",
        booking_history=history,
        preferences=current_prefs,
    )
    overall_summary = llm.invoke([HumanMessage(content=prompt)])

    updated_memory = {
        "preferences":     current_prefs,
        "summary":         overall_summary,
        "booking_history": history,
    }

    memory.save_user_memory(
        user_id=user_id,
        tenant_id=tenant_id,
        preferences=current_prefs,
        summary=overall_summary,
    )

    logger.info(f"  [NODE 8: SAVE_MEMORY] Saved conversation summary & updated patient user_memory profile.")
    return {"memory": updated_memory}
