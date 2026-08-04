"""
intent node — Classify user intent using LLM.
Updates conversation.intent. Nothing else.
"""

import logging
from langchain_core.messages import HumanMessage
from src.agent.state import AgentState
from src.agent.nodes._shared import llm, prompts

logger = logging.getLogger("agent_nodes")


def classify_intent(state: AgentState) -> dict:
    """Send user message to LLM → get intent → update conversation state."""
    prompt = prompts.get("intent", message=state["conversation"]["last_user_message"])
    intent = llm.invoke([HumanMessage(content=prompt)]).upper().strip()
    logger.info(f"  [NODE 2: CLASSIFY_INTENT] Input Message: '{state['conversation']['last_user_message']}' -> Intent: '{intent}'")
    return {"conversation": {**state["conversation"], "intent": intent}}
