"""
graph.py — LangGraph Workflow

Wires nodes together. No logic here — only structure.
Graph never knows about HTTP, LLM, MongoDB, or SQL.
Checkpointing enabled for conversation resume on crash.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from src.agent.state import AgentState
from src.agent import nodes, router


def build_graph():
    """Build and compile the hospital agent graph with checkpointing."""
    g = StateGraph(AgentState)

    # ── Register Nodes ─────────────────────────────────────────────────────
    g.add_node("load_memory",        nodes.load_memory)
    g.add_node("classify_intent",    nodes.classify_intent)
    g.add_node("extract_entities",   nodes.extract_entities)
    g.add_node("inject_memory",      nodes.inject_memory)
    g.add_node("validate",           nodes.validate)
    g.add_node("workflow_decision",  nodes.workflow_decision)    # NEW
    g.add_node("execute_tool",       nodes.execute_tool)
    g.add_node("generate_response",  nodes.generate_response)
    g.add_node("save_memory",        nodes.save_memory)

    # ── Entry Point ────────────────────────────────────────────────────────
    g.set_entry_point("load_memory")

    # ── Fixed Edges ────────────────────────────────────────────────────────
    g.add_edge("load_memory",       "classify_intent")
    g.add_edge("extract_entities",  "inject_memory")
    g.add_edge("inject_memory",     "validate")
    g.add_edge("save_memory",       "generate_response")
    g.add_edge("generate_response", END)

    # ── Conditional Edges ──────────────────────────────────────────────────
    g.add_conditional_edges("classify_intent",   router.after_intent)
    g.add_conditional_edges("validate",          router.after_validation)
    g.add_conditional_edges("workflow_decision", router.after_decision)   # NEW
    g.add_conditional_edges("execute_tool",      router.after_tool)

    # ── Checkpointing (conversation survives server restarts) ──────────────
    checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)


agent_graph = build_graph()
