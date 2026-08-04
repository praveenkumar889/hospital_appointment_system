"""
GraphRAG Query Engine for Doctor Appointment Booking.

Architecture:
  User Query
    ↓
  Intent Classifier (Claude)  →  identifies: find_doctor | get_info | book_appointment
    ↓
  Parallel Retrieval:
    ├── Vector Search (ChromaDB)   → semantic similarity to query
    └── Graph Traversal (Neo4j)    → structured relationships
    ↓
  Context Fusion
    ↓
  Response Synthesis (Claude)  →  structured appointment recommendation

Supports queries like:
  - "I need a heart doctor" → cardiology specialist
  - "Book appointment with Dr. Ajit Yadav"
  - "Orthopaedic surgeon with 25+ years experience"
  - "Who speaks Tamil and treats diabetes?"
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

import openai
from loguru import logger

from src.knowledge_base.config import get_settings, get_tenant_config
from src.knowledge_base.graph.neo4j_loader import Neo4jQueryEngine
from src.knowledge_base.rag.vector_store import VectorStore

settings = get_settings()


class QueryIntent(str, Enum):
    FIND_DOCTOR = "find_doctor"
    GET_DOCTOR_INFO = "get_doctor_info"
    BOOK_APPOINTMENT = "book_appointment"
    UNKNOWN = "unknown"


@dataclass
class QueryResult:
    intent: QueryIntent
    doctors: list[dict]
    context_text: str
    response: str
    booking_links: list[dict]


TENANT_INTENT_SYSTEM = """You are an intent classifier for {brand_name}, {brand_description}.
Classify the user's query into exactly one of these intents:
- find_doctor: User wants to find/discover doctors (by specialty, symptoms, condition)
- get_doctor_info: User wants details about a specific doctor they already know
- book_appointment: User explicitly wants to book/schedule an appointment
- unknown: None of the above

Also extract:
- specialization_keywords: list of medical specialties or conditions mentioned (e.g. ["orthopedics"] for knee pain, ["general medicine"] for fever)
- city: city or location mentioned if present (e.g. "Chennai", "Mumbai", "Hyderabad", "Bengaluru")
- doctor_name: specific doctor name if mentioned (null otherwise)
- preferences: dict of any preferences (language, experience, fee, location)

Respond ONLY with valid JSON. Example:
{
  "intent": "find_doctor",
  "specialization_keywords": ["cardiology", "heart"],
  "city": "Chennai",
  "doctor_name": null,
  "preferences": {"language": "Tamil", "min_experience": 10}
}"""

TENANT_RESPONSE_SYSTEM = """You are an AI assistant for {brand_name} appointment booking.
You help patients find the right doctor and guide them to book appointments.

When presenting doctors:
1. List the most relevant doctors with their key details
2. Include consultation fees, experience, and languages spoken
3. Always provide the booking URL or contact number: {contact_phone}
4. Be empathetic and professional
5. If the user wants to book, provide clear step-by-step instructions

Format responses in clear, readable text. Use bullet points for doctor listings.
Always end with a clear call-to-action for booking."""


class GraphRAGEngine:
    def __init__(
        self,
        vector_store: VectorStore,
        graph_engine: Neo4jQueryEngine,
        llm_client: openai.AsyncAzureOpenAI | None = None,
    ):
        self._vector = vector_store
        self._graph = graph_engine
        self._llm = llm_client or openai.AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )

    def _build_intent_system(self, tenant_id: str | None = None) -> str:
        tc = get_tenant_config(tenant_id)
        return tc.format(TENANT_INTENT_SYSTEM)

    def _build_response_system(self, tenant_id: str | None = None) -> str:
        tc = get_tenant_config(tenant_id)
        return tc.format(TENANT_RESPONSE_SYSTEM)

    async def classify_intent(self, query: str, tenant_id: str | None = None) -> dict:
        """Use Azure OpenAI to classify query intent and extract entities."""
        try:
            response = await self._llm.chat.completions.create(
                model=settings.azure_openai_deployment_name,
                messages=[
                    {"role": "system", "content": self._build_intent_system(tenant_id)},
                    {"role": "user", "content": query}
                ],
                max_tokens=512,
                temperature=0.0
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error(f"Intent classification error: {e}")
            return {
                "intent": "find_doctor",
                "specialization_keywords": [],
                "doctor_name": None,
                "preferences": {},
            }

    def _derive_tenant(self, tenant_id: str | None = None) -> str | None:
        """
        Derive tenant_id for GraphRAG queries.
        Maps group organization IDs (e.g., 'gleneagles' -> 'glh') or specific client branch IDs ('glh-chn').
        """
        if not tenant_id or tenant_id.lower() in ["gleneagles", "gleneagles hospitals", "all", "none"]:
            return "glh"
        return tenant_id

    async def retrieve(self, query: str, intent_data: dict, tenant_id: str | None = None) -> tuple[list[dict], list[dict]]:
        """
        Parallel retrieval from vector store (semantic) and graph (structured).
        Returns (vector_results, graph_results).
        """
        keywords = intent_data.get("specialization_keywords", [])
        doctor_name = intent_data.get("doctor_name")
        preferences = intent_data.get("preferences", {})
        tid = self._derive_tenant(tenant_id)

        # Build ChromaDB where filter (tenant isolation only; language is handled by semantic search)
        vector_filter = None
        if tid and tid != "glh":
            vector_filter = {"tenant_id": {"$eq": tid}}

        # Run vector + graph searches concurrently
        search_query = query
        if keywords:
            search_query = f"{query} {' '.join(keywords)}"

        vector_task = asyncio.create_task(
            asyncio.to_thread(self._vector.semantic_search, search_query, 25, vector_filter)
        )

        city_param = intent_data.get("city") or (intent_data.get("preferences") or {}).get("location") or (intent_data.get("preferences") or {}).get("city")

        if doctor_name:
            graph_task = asyncio.create_task(
                self._graph.find_by_fulltext(doctor_name, 10, tid, city_param)
            )
        elif keywords:
            # Try all keywords — specialization search across each, then fallback to fulltext
            async def _multi_keyword_search():
                all_results: list[dict] = []
                seen_ids: set[str] = set()
                for kw in keywords:
                    results = await self._graph.find_doctors_by_specialization(kw, 25, tid, city_param)
                    for r in results:
                        did = r.get("sql_id") or r.get("id") or r.get("name", "")
                        if did not in seen_ids:
                            seen_ids.add(did)
                            all_results.append(r)
                if not all_results:
                    # Fallback: fulltext search on the original query
                    all_results = await self._graph.find_by_fulltext(query, 25, tid, city_param)
                return all_results

            graph_task = asyncio.create_task(_multi_keyword_search())
        else:
            graph_task = asyncio.create_task(
                self._graph.find_by_fulltext(query, 25, tid, city_param)
            )

        try:
            graph_results = await graph_task
        except Exception as e:
            logger.warning(f"Graph search exception (falling back gracefully): {e}")
            graph_results = []

        try:
            vector_results = await asyncio.wait_for(vector_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Vector search bypassed or timed out: {e}")
            vector_results = []

        return vector_results, graph_results

    def _fuse_results(
        self, vector_results: list[dict], graph_results: list[dict], intent_data: dict | None = None, n: int = 20
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion of vector + graph results.
        Higher score = better match.
        """
        scores: dict[str, float] = {}
        doc_data: dict[str, dict] = {}

        k = 60  # RRF constant

        for rank, r in enumerate(vector_results):
            did = r["metadata"].get("doctor_id", r["id"])
            scores[did] = scores.get(did, 0) + 1 / (k + rank + 1)
            if did not in doc_data:
                doc_data[did] = {
                    "doctor_id": did,
                    "name": r["metadata"].get("name") or r["metadata"].get("doctor_name", ""),
                    "specializations": r["metadata"].get("specializations", ""),
                    "experience_years": r["metadata"].get("experience_years"),
                    "consultation_fee": r["metadata"].get("consultation_fee"),
                    "designation": r["metadata"].get("designation", ""),
                    "languages": r["metadata"].get("languages", ""),
                    "hospital_ids": r["metadata"].get("hospital_ids", ""),
                    "context_text": r["text"],
                }

        for rank, r in enumerate(graph_results):
            did = r.get("sql_id") or r.get("id") or r.get("doctor_id") or ""
            if not did:
                continue
            scores[did] = scores.get(did, 0) + 1 / (k + rank + 1)
            if did not in doc_data:
                doc_data[did] = r
            else:
                # Merge graph data (more complete) into existing record
                doc_data[did].update({k: v for k, v in r.items() if v})

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        # Boost and prioritize doctors matching requested specialization keywords
        spec_kw = intent_data.get("specialization_keywords") or []
        stop_words = {"department", "doctor", "hospital", "medicine", "care", "specialist", "appointment", "clinic", "consultant"}
        kw_lower = [k.lower() for k in spec_kw if len(k) >= 3 and k.lower() not in stop_words]
        
        matched_docs = []
        other_docs = []
        for did in sorted_ids:
            doc = doc_data[did]
            specs_raw = doc.get("specializations") or doc.get("speciality") or doc.get("department") or ""
            specs = (" ".join(specs_raw) if isinstance(specs_raw, (list, tuple, set)) else str(specs_raw)).lower()
            if kw_lower and any(k in specs for k in kw_lower):
                matched_docs.append(doc)
            else:
                other_docs.append(doc)
        
        # If exact department matches exist, use them exclusively for precise targeting
        fused_candidates = matched_docs if matched_docs else other_docs

        # Multi-Branch Round-Robin Selection: Ensure doctors from ALL branches in the city are displayed!
        branch_groups: dict[str, list[dict]] = {}
        for doc in fused_candidates:
            hosps = doc.get("hospitals") or ["Gleneagles Hospital"]
            b_name = hosps[0] if isinstance(hosps, list) and hosps else str(hosps)
            branch_groups.setdefault(b_name, []).append(doc)

        final_fused = []
        while len(final_fused) < n and any(branch_groups.values()):
            for b_name in list(branch_groups.keys()):
                if branch_groups[b_name]:
                    final_fused.append(branch_groups[b_name].pop(0))
                if len(final_fused) >= n:
                    break

        return final_fused

    def _enrich_from_sqlite(self, docs: list[dict]) -> list[dict]:
        """Enrich fused doctor records with qualifications, consultation_fee, full hospital name & branch from SQLite."""
        if not docs:
            return docs
        import sqlite3
        try:
            conn = sqlite3.connect("src/workflows/data/db/knowledge_base.db")
            cursor = conn.cursor()
            for doc in docs:
                did = doc.get("sql_id") or doc.get("doctor_id") or doc.get("id") or ""
                name = doc.get("name") or doc.get("doctor_name") or ""
                row = None
                if did:
                    cursor.execute("""
                        SELECT d.qualifications, d.consultation_fee, d.designation, d.experience_years, d.languages, h.name, h.branch, h.city 
                        FROM doctors d 
                        LEFT JOIN hospitals h ON h.id = d.tenant_id OR h.tenant_id = d.tenant_id
                        WHERE d.id = ?
                    """, (did,))
                    row = cursor.fetchone()
                if not row and name:
                    cursor.execute("""
                        SELECT d.qualifications, d.consultation_fee, d.designation, d.experience_years, d.languages, h.name, h.branch, h.city 
                        FROM doctors d 
                        LEFT JOIN hospitals h ON h.id = d.tenant_id OR h.tenant_id = d.tenant_id
                        WHERE d.name LIKE ?
                    """, (f"%{name}%",))
                    row = cursor.fetchone()
                if row:
                    if row[0]: doc["qualifications"] = row[0]
                    if row[1]: doc["consultation_fee"] = row[1]
                    if row[2]: doc["designation"] = row[2]
                    if row[3]: doc["experience_years"] = row[3]
                    if row[4]: doc["languages"] = row[4]
                    h_name, h_branch, h_city = row[5], row[6], row[7]
                    if h_name or h_branch:
                        full_branch = h_branch if (h_branch and len(h_branch) > len(str(h_name))) else f"{h_name}, {h_city}" if (h_name and h_city) else (h_name or h_branch)
                        doc["hospital_name"] = full_branch
                        doc["branch_name"]   = full_branch
                        doc["branch"]        = full_branch
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to enrich doctor details from SQLite: {e}")
        return docs

    def _build_context(self, fused: list[dict], intent_data: dict, tenant_id: str | None = None) -> str:
        """Build a structured context string for Claude synthesis."""
        tc = get_tenant_config(tenant_id)
        if not fused:
            return f"No matching {tc.item_noun_plural} found in the knowledge base."

        lines = [f"RELEVANT {tc.item_noun_plural.upper()} FROM KNOWLEDGE BASE:\n"]
        for i, doc in enumerate(fused, 1):
            name = doc.get("name") or doc.get("doctor_name", "Unknown")
            specs_raw = doc.get("specializations", "")
            if isinstance(specs_raw, str):
                specs_raw = [s.strip() for s in specs_raw.split(",") if s.strip()]
            cleaned_specs = []
            for s in (specs_raw if isinstance(specs_raw, list) else [str(specs_raw)]):
                if s:
                    val = s.strip().title()
                    if val not in cleaned_specs:
                        cleaned_specs.append(val)
            specs = ", ".join(cleaned_specs) if cleaned_specs else str(doc.get("specialization") or doc.get("department") or "")
            exp = doc.get("experience_years")
            fee = doc.get("consultation_fee")
            quals = doc.get("qualifications")
            langs = doc.get("languages", "")
            if isinstance(langs, list):
                langs = ", ".join(langs)
            desig = doc.get("designation", "Consultant")
            hosp = doc.get("hospitals", doc.get("hospital_ids", tc.brand_name))
            if isinstance(hosp, list):
                hosp = ", ".join(
                    (h.get("name", "") + " " + h.get("location", "")).strip()
                    if isinstance(h, dict) else str(h)
                    for h in hosp
                )

            lines.append(f"{i}. {name}")
            lines.append(f"   Designation: {desig}")
            lines.append(f"   Specialization: {specs}")
            if quals:
                lines.append(f"   Qualification: {quals}")
            if exp:
                lines.append(f"   Experience: {exp} years")
            if fee:
                try:
                    lines.append(f"   Consultation Fee: {tc.currency_symbol}{int(fee)}")
                except (ValueError, TypeError):
                    lines.append(f"   Consultation Fee: {tc.currency_symbol}{fee}")
            if langs:
                lines.append(f"   Languages: {langs}")
            lines.append(f"   Hospital: {hosp}")

            booking = doc.get("booking_url") or doc.get("profile_url", "")
            if booking:
                lines.append(f"   Booking: {booking}")

            # Include context text if available
            ctx = doc.get("context_text", "")
            if ctx and len(ctx) > 50:
                lines.append(f"   ---")
                lines.append(f"   {ctx[:300]}")

            lines.append("")

        return "\n".join(lines)

    async def synthesize_response(self, query: str, context: str, intent_data: dict, tenant_id: str | None = None) -> str:
        """Use Azure OpenAI to generate a helpful appointment booking response."""
        intent = intent_data.get("intent", "find_doctor")

        if intent == QueryIntent.BOOK_APPOINTMENT:
            task_hint = "The user wants to BOOK an appointment. Guide them step-by-step."
        elif intent == QueryIntent.GET_DOCTOR_INFO:
            task_hint = "The user wants detailed information about a specific doctor."
        else:
            task_hint = "Help the user find the right doctor for their needs."

        prompt = f"""User Query: {query}

{task_hint}

{context}

Please provide a helpful, empathetic response that:
1. Directly addresses the user's query
2. Recommends the most suitable doctor(s) from the context
3. Includes key details (fee, experience, languages, hospital)
4. Provides clear next steps to book an appointment"""

        try:
            response = await self._llm.chat.completions.create(
                model=settings.azure_openai_deployment_name,
                messages=[
                    {"role": "system", "content": self._build_response_system(tenant_id)},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1024,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Response synthesis error: {e}")
            tc = get_tenant_config(tenant_id)
            return f"Based on your query, here are relevant {tc.item_noun_plural}:\n\n{context}"

    async def query(self, user_query: str, tenant_id: str | None = None, n: int = 20) -> QueryResult:
        """Full GraphRAG pipeline: classify → retrieve → fuse → synthesize."""
        logger.info(f"GraphRAG query: {user_query!r} (tenant={tenant_id}, n={n})")

        # Step 1: Classify intent
        intent_data = await self.classify_intent(user_query, tenant_id)
        intent = QueryIntent(intent_data.get("intent", "unknown"))
        logger.info(f"Intent: {intent}, keywords: {intent_data.get('specialization_keywords')}")

        # Step 2: Parallel retrieval
        vector_results, graph_results = await self.retrieve(user_query, intent_data, tenant_id)
        logger.info(f"Retrieved: {len(vector_results)} vector, {len(graph_results)} graph")

        # Step 3: Fuse, rank, and enrich from SQLite
        fused = self._fuse_results(vector_results, graph_results, intent_data, n=n)
        fused = self._enrich_from_sqlite(fused)

        # Step 4: Build context
        context_text = self._build_context(fused, intent_data, tenant_id)

        # Step 5: Synthesize response
        response = await self.synthesize_response(user_query, context_text, intent_data, tenant_id)

        # Step 6: Extract booking links
        booking_links = [
            {
                "doctor_id": d.get("doctor_id", d.get("id", "")),
                "name": d.get("name") or d.get("doctor_name", ""),
                "booking_url": d.get("booking_url") or d.get("profile_url", ""),
                "fee": d.get("consultation_fee"),
            }
            for d in fused
            if d.get("booking_url") or d.get("profile_url")
        ]

        return QueryResult(
            intent=intent,
            doctors=fused,
            context_text=context_text,
            response=response,
            booking_links=booking_links,
        )
