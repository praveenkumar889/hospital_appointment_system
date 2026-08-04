"""
/doctors routes — individual doctor profiles and chunks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.knowledge_base.api.dependencies import get_graph_engine, get_vector_store
from src.knowledge_base.graph.neo4j_loader import Neo4jQueryEngine
from src.knowledge_base.rag.vector_store import VectorStore

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("/{doctor_id}")
async def get_doctor(
    doctor_id: str,
    graph: Neo4jQueryEngine = Depends(get_graph_engine),
):
    """Full semantic context for a doctor (specializations, hospitals, languages)."""
    doc = await graph.get_doctor_context(doctor_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Doctor '{doctor_id}' not found")
    return doc


@router.get("/{doctor_id}/chunks")
async def get_doctor_chunks(
    doctor_id: str,
    store: VectorStore = Depends(get_vector_store),
):
    """Raw text chunks stored in the vector store for this doctor."""
    import asyncio
    chunks = await asyncio.to_thread(store.search_by_doctor_id, doctor_id)
    return {"doctor_id": doctor_id, "chunks": chunks}
