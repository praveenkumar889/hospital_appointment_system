"""
main.py — Workflows API Server

Port: 8001
Endpoints:
  GET  /appointments/availability
  POST /appointments/book
  POST /appointments/reschedule
  POST /appointments/cancel
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.workflows.api.endpoints import router as appointment_router

app = FastAPI(
    title="Hospital Workflows API",
    description="Appointment booking, slot availability, reschedule, and cancellation service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appointment_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "workflows-api", "port": 8001}


if __name__ == "__main__":
    uvicorn.run("src.workflows.api.main:app", host="0.0.0.0", port=8001, reload=True)
