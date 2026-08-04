"""Application setup - imports and middleware only"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.workflows.api.endpoints import router, actions_router

app = FastAPI(title="Hospital Appointment Booking API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ✅ Include BOTH routers
app.include_router(router)        # Existing /appointments routes
app.include_router(actions_router) # ✅ NEW: /actions route for Orchestrator

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.workflows.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("WORKFLOWS_API_PORT", "8001")),
        reload=False,
    )