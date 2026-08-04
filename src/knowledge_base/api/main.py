"""
FastAPI application entry point for the Doctor Appointment Knowledge Base.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.knowledge_base.api.routes import search_router, doctors_router, appointment_router
from src.knowledge_base.api.routes import search_router, doctors_router, appointment_router
from src.knowledge_base.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Doctor Appointment KB API...")
    yield
    logger.info("Shutting down API.")


app = FastAPI(
    title="Doctor Appointment Knowledge Base API",
    description=(
        "GraphRAG-powered API for AI-driven doctor appointment booking. "
        "Combines Neo4j knowledge graph with ChromaDB semantic search."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(doctors_router)
app.include_router(appointment_router)


@app.get("/", tags=["health"])
async def root():
    return {
        "service": "Doctor Appointment Knowledge Base",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "graphrag_search": "POST /appointment/assist",
            "semantic_search": "GET /search/doctors?q=...",
            "by_specialization": "GET /search/doctors/by-specialization?specialization=...",
            "doctor_profile": "GET /doctors/{doctor_id}",
            "booking_context": "GET /doctors/{doctor_id}/appointment-context",
        },
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
