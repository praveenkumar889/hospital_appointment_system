"""
app.py — Agent FastAPI Server Entry Point

Endpoints:
  POST /chat  → runs agent graph → returns reply
  POST /reset → resets session state
"""

import uuid
import uvicorn
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

import config
from src.agent.graph import agent_graph
from src.utils.helpers import build_initial_state

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("agent_api")


# ── App Setup ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Hospital Agent API",
    description="LangGraph-powered multi-tenant hospital appointment assistant",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None
    user_id:    Optional[str] = None
    tenant_id:  Optional[str] = None


class ChatResponse(BaseModel):
    reply:          str
    session_id:     str
    user_id:        str
    intent:         Optional[str] = None
    appointment_id: Optional[str] = None
    needs_info:     list          = []


class ResetRequest(BaseModel):
    user_id:   Optional[str] = None
    tenant_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Request, Header
from src.utils.tenant_resolver import TenantResolver

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, x_tenant_id: Optional[str] = Header(None)):
    """
    Main chat endpoint.
    1. Resolve tenant_id dynamically (Header / Phone / Domain / Explicit).
    2. Build initial agent state from incoming message.
    3. Run the LangGraph agent.
    4. Return structured response.
    """
    try:
        session_id = req.session_id or str(uuid.uuid4())
        user_id    = req.user_id    or session_id
        
        # Dynamic Tenant Resolution BEFORE LangGraph
        tenant_id  = TenantResolver.resolve(
            explicit_tenant=req.tenant_id,
            header_tenant=x_tenant_id,
            hostname=request.headers.get("host"),
        )

        logger.info("================================================================================")
        logger.info(f"[TERMINAL 3: LANGGRAPH AGENT SERVER | File: src/agent/app.py]")
        logger.info(f"  ↳ RECEIVED FROM TERMINAL 4 (WhatsApp UI): User={user_id} | Session={session_id} | Tenant={tenant_id}")
        logger.info(f"  ↳ USER MESSAGE: {req.message!r}")
        logger.info(f"  ↳ STARTING LANGGRAPH AGENT EXECUTION (src/agent/graph.py)...")

        initial = build_initial_state(session_id, tenant_id, req.message, user_id=user_id)
        result  = agent_graph.invoke(
            initial,
            config={"configurable": {"thread_id": session_id}},
        )

        intent     = result["conversation"].get("intent")
        action     = result["runtime"].get("next_action")
        needs_info = result["runtime"].get("needs_info", [])
        reply      = result["conversation"]["last_response"]

        logger.info(f"[TERMINAL 3: LANGGRAPH AGENT SERVER | File: src/agent/app.py]")
        logger.info(f"  ↳ AGENT PIPELINE COMPLETE: Intent={intent} | Action={action} | Needs={needs_info}")
        logger.info(f"  ↳ RETURNING AGENT RESPONSE TO TERMINAL 4: {reply!r}")
        logger.info("================================================================================")

        return ChatResponse(
            reply          = reply,
            session_id     = session_id,
            user_id        = result["user_id"],
            intent         = intent,
            appointment_id = result["workflow"]["data"].get("appointment_id"),
            needs_info     = needs_info,
        )
    except Exception as e:
        logger.error(f"[TERMINAL 3 AGENT SERVER ERROR] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset")
async def reset(req: ResetRequest):
    """Reset session state endpoint."""
    logger.info(f"[TERMINAL 3 RESET] Resetting session for user: {req.user_id}")
    return {"status": "ok", "message": "Session reset successfully"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "hospital-agent", "version": "1.0.0"}


# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("src.agent.app:app", host=config.APP_HOST, port=config.APP_PORT, reload=True)
