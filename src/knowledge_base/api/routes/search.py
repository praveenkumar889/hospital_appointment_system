"""
/search routes — semantic + graph search for doctors.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query

from src.knowledge_base.api.dependencies import get_graphrag_engine, get_vector_store, get_graph_engine
from src.knowledge_base.query.graphrag_engine import GraphRAGEngine
from src.knowledge_base.rag.vector_store import VectorStore
from src.knowledge_base.graph.neo4j_loader import Neo4jQueryEngine

logger = logging.getLogger("kb_api")
router = APIRouter(prefix="/search", tags=["search"])


@router.get("/doctors")
async def search_doctors(
    q: str = Query(..., description="Natural language query, e.g. 'heart specialist Tamil speaking'"),
    n: int = Query(20, ge=1, le=50, description="Number of results"),
    tenant_id: Optional[str] = Query(None, description="Tenant filter (e.g. 'gleneagles', 'inventaa')"),
    engine: GraphRAGEngine = Depends(get_graphrag_engine),
):
    """
    GraphRAG search: combines semantic vector search with Neo4j graph traversal.
    Returns ranked list of matching doctors with booking links.
    """
    logger.info("================================================================================")
    logger.info(f"[TERMINAL 1: KNOWLEDGE BASE API | File: src/knowledge_base/api/routes/search.py]")
    logger.info(f"  ↳ RECEIVED HTTP GET FROM TERMINAL 3 (Agent DoctorSearchTool)")
    logger.info(f"  ↳ QUERY: {q!r} | Tenant: {tenant_id!r} | Limit: {n}")

    try:
        result = await engine.query(q, tenant_id=tenant_id, n=n)
        doctors_data = result.doctors[:n]
        intent_val   = result.intent
        links_data   = result.booking_links[:n]
        ai_resp      = result.response
    except Exception as e:
        logger.warning(f"[TERMINAL 1 WARN] GraphRAG query exception handled gracefully: {e}")
        import sqlite3
        conn = sqlite3.connect("src/workflows/data/db/knowledge_base.db")
        cursor = conn.cursor()
        query_term = f"%{q.split()[0]}%" if q else "%"
        cursor.execute("""
            SELECT d.id, d.name, d.speciality, h.name, h.city
            FROM doctors d
            LEFT JOIN hospitals h ON d.location_id = h.location_id
            WHERE (d.name LIKE ? OR d.speciality LIKE ?)
            LIMIT ?
        """, (query_term, query_term, n))
        rows = cursor.fetchall()
        conn.close()
        doctors_data = [{
            "doctor_id": r[0], "name": r[1], "specialization": r[2] or "General",
            "hospital_name": r[3] or "Gleneagles Hospitals", "city": r[4] or "Hyderabad"
        } for r in rows]
        intent_val = "DOCTOR_SEARCH"
        links_data = []
        ai_resp = f"Retrieved {len(doctors_data)} doctor(s)."

    logger.info(f"[TERMINAL 1: KNOWLEDGE BASE API | File: src/knowledge_base/api.routes.search]")
    logger.info(f"  ↳ GraphRAG RESULT: Intent={intent_val!r} | Doctors Found={len(doctors_data)}")
    logger.info(f"  ↳ RETURNING RESPONSE TO TERMINAL 3")
    logger.info("================================================================================")

    return {
        "query": q,
        "intent": intent_val,
        "doctors": doctors_data,
        "booking_links": links_data,
        "ai_response": ai_resp,
    }


@router.get("/doctors/semantic")
async def semantic_search(
    q: str = Query(..., description="Natural language query"),
    n: int = Query(5, ge=1, le=20),
    store: VectorStore = Depends(get_vector_store),
):
    """Pure semantic vector search (no graph traversal)."""
    results = store.semantic_search(q, n_results=n)
    return {"query": q, "results": results}


@router.get("/doctors/by-specialty")
async def doctors_by_specialty(
    specialty: str = Query(..., description="Specialty name, e.g. 'Cardiology'"),
    limit: int = Query(10, ge=1, le=50),
    engine: Neo4jQueryEngine = Depends(get_graph_engine),
):
    """Graph search by specialty name."""
    doctors = await engine.find_doctors_by_specialization(specialty, limit=limit)
    return {"specialty": specialty, "doctors": doctors}
