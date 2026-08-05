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
        import sqlite3, re
        conn = sqlite3.connect("src/workflows/data/db/knowledge_base.db")
        cursor = conn.cursor()
        
        tokens = [t.lower() for t in re.findall(r'\b[A-Za-z]{4,}\b', q)]
        stop_words = {"find", "show", "need", "want", "doctor", "specialist", "speaks", "chennai", "perumbakkam"}
        spec_tokens = [t for t in tokens if t not in stop_words]
        search_stem = spec_tokens[0][:4] if spec_tokens else (tokens[0][:4] if tokens else "%")
        
        cursor.execute("""
            SELECT d.id, d.name, d.speciality, d.specializations, d.designation, d.qualifications, d.consultation_fee, d.experience_years, d.languages, h.name, h.branch, h.city
            FROM doctors d
            LEFT JOIN hospitals h ON h.id = d.tenant_id OR h.tenant_id = d.tenant_id OR (d.id LIKE '%chn' AND h.id = 'glh-chn')
            WHERE (d.name LIKE ? OR d.speciality LIKE ? OR d.specializations LIKE ?)
            LIMIT ?
        """, (f"%{search_stem}%", f"%{search_stem}%", f"%{search_stem}%", n))
        rows = cursor.fetchall()
        conn.close()
        
        doctors_data = []
        for r in rows:
            hosp_val = r[10] if (r[10] and len(r[10]) > len(str(r[9]))) else f"{r[9]}, {r[11]}" if (r[9] and r[11]) else r[9]
            doctors_data.append({
                "doctor_id":        r[0],
                "doctor_name":      r[1],
                "department":       r[2] or r[3],
                "specialization":   r[3] or r[2],
                "designation":      r[4] or "",
                "qualifications":   r[5] or "",
                "consultation_fee": f"₹{r[6]}" if r[6] and not str(r[6]).startswith("₹") else str(r[6] or ""),

                "experience_years": r[7],
                "languages":        r[8] or "",
                "branch_name":      hosp_val,
                "hospital_name":    hosp_val,
                "branch":           hosp_val,
            })
        links_data = []
        ai_resp = f"Here are the available doctors for your query: {q}"

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
