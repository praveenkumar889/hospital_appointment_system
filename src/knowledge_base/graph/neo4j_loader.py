"""
src/graph/neo4j_loader.py

Semantic-only graph in Neo4j AuraDB.

Nodes:   Doctor, Hospital, Specialization, Language
Edges:   PRACTICES_AT, SPECIALIZES_IN, SPEAKS

No schedule data here — availability lives entirely in SQLite (schedule_days / time_slots).
Every Doctor node carries sql_id = SQL doctors.id for cross-store retrieval.
"""

from __future__ import annotations

from loguru import logger
from neo4j import AsyncGraphDatabase, AsyncDriver

from src.knowledge_base.config import get_settings

settings = get_settings()


class Neo4jLoader:
    def __init__(self, uri: str, username: str, password: str, database: str):
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            liveness_check_timeout=30,
            max_connection_lifetime=180,
            max_connection_pool_size=50,
            connection_timeout=10.0,
        )
        self._db = database

    def _session(self):
        return self._driver.session(database=self._db)

    async def close(self):
        await self._driver.close()

    # ── Schema ─────────────────────────────────────────────────────────────────

    async def apply_schema(self) -> None:
        statements = [
            "CREATE CONSTRAINT doctor_id_unique   IF NOT EXISTS FOR (d:Doctor)         REQUIRE d.id   IS UNIQUE",
            "CREATE CONSTRAINT hospital_id_unique IF NOT EXISTS FOR (h:Hospital)        REQUIRE h.id   IS UNIQUE",
            "CREATE CONSTRAINT spec_name_unique   IF NOT EXISTS FOR (s:Specialization)  REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT lang_name_unique   IF NOT EXISTS FOR (l:Language)        REQUIRE l.name IS UNIQUE",
            # Full-text index for doctor name / designation search
            "CREATE FULLTEXT INDEX doctor_ft IF NOT EXISTS FOR (d:Doctor) ON EACH [d.name, d.designation]",
            "CREATE FULLTEXT INDEX spec_ft   IF NOT EXISTS FOR (s:Specialization) ON EACH [s.name]",
            "CREATE INDEX doctor_name_idx    IF NOT EXISTS FOR (d:Doctor) ON (d.name)",
        ]
        async with self._session() as session:
            for stmt in statements:
                try:
                    await session.run(stmt)
                except Exception as exc:
                    logger.warning(f"Schema stmt skipped: {exc}")
        logger.info("Neo4j schema applied")

    # ── Clear ──────────────────────────────────────────────────────────────────

    async def clear_all(self) -> None:
        async with self._session() as session:
            await session.run("MATCH (n) DETACH DELETE n")
        logger.info("Neo4j: all nodes and relationships deleted")

    # ── Hospital ───────────────────────────────────────────────────────────────

    def _tenant_from_hospitals(self, hospital_ids: list[str]) -> str:
        """Derive tenant_id from hospital IDs — matches the hospital_id field in TENANT_META."""
        from src.knowledge_base.config import TENANT_META
        for hid in (hospital_ids or []):
            for tid, meta in TENANT_META.items():
                if meta["hospital_id"] == hid:
                    return tid
        return "glh-chn"

    async def upsert_hospital(self, h: dict) -> None:
        async with self._session() as session:
            await session.run(
                """
                MERGE (h:Hospital {id: $id})
                SET h.name        = $name,
                    h.branch      = $branch,
                    h.city        = $city,
                    h.state       = $state,
                    h.location_id = $location_id,
                    h.tenant_id   = $tenant_id,
                    h.sql_id      = $id
                """,
                id=h["id"],
                name=h.get("name", ""),
                branch=h.get("branch"),
                city=h.get("city"),
                state=h.get("state"),
                location_id=h.get("location_id"),
                tenant_id=self._tenant_from_hospitals([h.get("id", "")]),
            )

    # ── Doctor + semantic edges ────────────────────────────────────────────────

    async def upsert_doctor(self, doc: dict) -> None:
        """
        MERGE Doctor node (identity only).
        Semantic edges: PRACTICES_AT → Hospital, SPECIALIZES_IN → Specialization, SPEAKS → Language.
        All transactional/schedule data stays in SQL.
        """
        tenant_id = doc.get("tenant_id") or self._tenant_from_hospitals(doc.get("hospital_ids", []))
        async with self._session() as session:
            await session.run(
                """
                MERGE (d:Doctor {id: $id})
                SET d.name             = $name,
                    d.designation      = $designation,
                    d.gender           = $gender,
                    d.appointment_type = $appointment_type,
                    d.experience_years = $experience_years,
                    d.tenant_id        = $tenant_id,
                    d.sql_id           = $id
                """,
                id=doc["id"],
                name=doc.get("name", ""),
                designation=doc.get("designation"),
                gender=doc.get("gender"),
                appointment_type=doc.get("appointment_type"),
                experience_years=doc.get("experience_years"),
                tenant_id=tenant_id,
            )

            # PRACTICES_AT → Hospital
            for hid in (doc.get("hospital_ids") or []):
                await session.run(
                    """
                    MATCH (d:Doctor {id: $did}), (h:Hospital {id: $hid})
                    MERGE (d)-[:PRACTICES_AT]->(h)
                    """,
                    did=doc["id"], hid=hid,
                )

            # SPECIALIZES_IN → Specialization
            for spec in (doc.get("specializations") or []):
                spec = spec.strip()
                if not spec:
                    continue
                await session.run(
                    """
                    MERGE (s:Specialization {name: $name})
                    WITH s
                    MATCH (d:Doctor {id: $did})
                    MERGE (d)-[:SPECIALIZES_IN]->(s)
                    """,
                    name=spec, did=doc["id"],
                )

            # SPEAKS → Language
            for lang in (doc.get("languages") or []):
                lang = lang.strip()
                if not lang:
                    continue
                await session.run(
                    """
                    MERGE (l:Language {name: $name})
                    WITH l
                    MATCH (d:Doctor {id: $did})
                    MERGE (d)-[:SPEAKS]->(l)
                    """,
                    name=lang, did=doc["id"],
                )

    # ── Batch loaders ──────────────────────────────────────────────────────────

    async def load_hospitals(self, hospitals: list[dict]) -> None:
        for h in hospitals:
            await self.upsert_hospital(h)
        logger.info(f"Neo4j: {len(hospitals)} hospitals loaded")

    async def load_doctors(self, doctors: list[dict], batch_log: int = 50) -> None:
        for i, doc in enumerate(doctors):
            await self.upsert_doctor(doc)
            if (i + 1) % batch_log == 0:
                logger.info(f"  Neo4j doctors: {i+1}/{len(doctors)}")
        logger.success(f"Neo4j: {len(doctors)} doctors loaded")


# ── Query engine (semantic lookups only) ──────────────────────────────────────

class Neo4jQueryEngine:
    """
    Semantic graph queries. Results contain sql_id so callers can join to SQLite
    for schedule availability and transactional details.
    """

    def __init__(self, driver: AsyncDriver, database: str):
        self._driver = driver
        self._db = database

    def _session(self):
        return self._driver.session(database=self._db)

    async def find_doctors_by_specialization(self, specialization: str, limit: int = 20, tenant_id: str | None = None, city: str | None = None) -> list[dict]:
        """Find doctors by full-text search on specialization names, optionally filtered by tenant and city."""
        root = specialization[:5].lower() if len(specialization) >= 5 else specialization.lower()
        lucene_query = f"{specialization} OR {root}*" if root != specialization.lower() else specialization
        try:
            async with self._session() as session:
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('spec_ft', $spec) YIELD node AS s, score
                    MATCH (d:Doctor)-[:SPECIALIZES_IN]->(s)
                    MATCH (d)-[:PRACTICES_AT]->(h:Hospital)
                    WHERE ($tenant_id IS NULL OR d.tenant_id STARTS WITH $tenant_id)
                      AND ($city IS NULL OR toLower(h.city) CONTAINS toLower($city))
                    OPTIONAL MATCH (d)-[:SPEAKS]->(l:Language)
                    RETURN d.sql_id AS sql_id, d.name AS name, d.designation AS designation,
                           d.experience_years AS experience_years,
                           d.rating_score AS rating_score,
                           d.tenant_id AS tenant_id,
                           collect(DISTINCT s.name) AS specializations,
                           collect(DISTINCT h.name) AS hospitals,
                           collect(DISTINCT h.city)  AS cities,
                           collect(DISTINCT l.name)  AS languages
                    ORDER BY d.experience_years DESC
                    LIMIT $limit
                    """,
                    spec=lucene_query, limit=limit, tenant_id=tenant_id, city=city,
                )
                return await result.data()
        except Exception as e:
            logger.warning(f"[NEO4J WARN] find_doctors_by_specialization exception (handled gracefully): {e}")
            return []

    async def find_doctors_by_language(self, language: str, limit: int = 20, tenant_id: str | None = None) -> list[dict]:
        """Find doctors who SPEAKS the given language, optionally filtered by tenant."""
        try:
            async with self._session() as session:
                result = await session.run(
                    """
                    MATCH (d:Doctor)-[:SPEAKS]->(l:Language)
                    WHERE toLower(l.name) CONTAINS toLower($lang)
                    """ + ("""
                    AND d.tenant_id STARTS WITH $tenant_id
                    """ if tenant_id else "") + """
                    OPTIONAL MATCH (d)-[:SPECIALIZES_IN]->(s:Specialization)
                    OPTIONAL MATCH (d)-[:PRACTICES_AT]->(h:Hospital)
                    RETURN d.sql_id AS sql_id, d.name AS name, d.designation AS designation,
                           d.experience_years AS experience_years,
                           d.rating_score AS rating_score,
                           d.tenant_id AS tenant_id,
                           collect(DISTINCT s.name) AS specializations,
                           collect(DISTINCT h.name) AS hospitals,
                           collect(DISTINCT h.city)  AS cities,
                           collect(DISTINCT l.name)  AS languages
                    ORDER BY d.name
                    LIMIT $limit
                    """,
                    lang=language, limit=limit, tenant_id=tenant_id,
                )
                return await result.data()
        except Exception as e:
            logger.warning(f"[NEO4J WARN] find_doctors_by_language exception (handled gracefully): {e}")
            return []

    async def find_by_fulltext(self, keyword: str, limit: int = 20, tenant_id: str | None = None, city: str | None = None) -> list[dict]:
        """Full-text search on doctor name and designation, optionally filtered by tenant and city."""
        try:
            async with self._session() as session:
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('doctor_ft', $kw) YIELD node AS d, score
                    MATCH (d)-[:PRACTICES_AT]->(h:Hospital)
                    WHERE ($tenant_id IS NULL OR d.tenant_id STARTS WITH $tenant_id)
                      AND ($city IS NULL OR toLower(h.city) CONTAINS toLower($city))
                    OPTIONAL MATCH (d)-[:SPECIALIZES_IN]->(s:Specialization)
                    OPTIONAL MATCH (d)-[:SPEAKS]->(l:Language)
                    RETURN d.sql_id AS sql_id, d.name AS name, d.designation AS designation,
                           d.experience_years AS experience_years,
                           d.rating_score AS rating_score,
                           d.tenant_id AS tenant_id,
                           score,
                           collect(DISTINCT s.name) AS specializations,
                           collect(DISTINCT h.name) AS hospitals,
                           collect(DISTINCT h.city)  AS cities,
                           collect(DISTINCT l.name)  AS languages
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    kw=keyword, limit=limit, tenant_id=tenant_id, city=city,
                )
                return await result.data()
        except Exception as e:
            logger.warning(f"[NEO4J WARN] find_by_fulltext exception (handled gracefully): {e}")
            return []

    async def get_doctor_context(self, doctor_id: str) -> dict | None:
        """Full semantic context for one doctor (for RAG). Caller joins SQL for slots."""
        async with self._session() as session:
            result = await session.run(
                """
                MATCH (d:Doctor {id: $id})
                OPTIONAL MATCH (d)-[:SPECIALIZES_IN]->(s:Specialization)
                OPTIONAL MATCH (d)-[:PRACTICES_AT]->(h:Hospital)
                OPTIONAL MATCH (d)-[:SPEAKS]->(l:Language)
                RETURN d.sql_id AS sql_id, d.name AS name,
                       d.designation AS designation,
                       d.experience_years AS experience_years,
                       d.gender AS gender,
                       d.appointment_type AS appointment_type,
                       collect(DISTINCT s.name)                          AS specializations,
                       collect(DISTINCT {name: h.name, city: h.city})   AS hospitals,
                       collect(DISTINCT l.name)                          AS languages
                """,
                id=doctor_id,
            )
            row = await result.single()
        return dict(row) if row else None

    async def colleagues_by_specialty(self, doctor_id: str, limit: int = 10) -> list[dict]:
        """Doctors sharing specialization and hospital with the given doctor."""
        async with self._session() as session:
            result = await session.run(
                """
                MATCH (d:Doctor {id: $did})-[:SPECIALIZES_IN]->(s:Specialization)
                MATCH (d)-[:PRACTICES_AT]->(h:Hospital)
                MATCH (c:Doctor)-[:SPECIALIZES_IN]->(s)
                MATCH (c)-[:PRACTICES_AT]->(h)
                WHERE c.id <> $did
                RETURN DISTINCT c.sql_id AS sql_id, c.name AS name,
                       c.designation AS designation,
                       s.name AS shared_specialty,
                       h.name AS hospital
                LIMIT $limit
                """,
                did=doctor_id, limit=limit,
            )
            return await result.data()

    async def get_doctors_at_hospital(self, hospital_id: str, limit: int = 100) -> list[dict]:
        async with self._session() as session:
            result = await session.run(
                """
                MATCH (d:Doctor)-[:PRACTICES_AT]->(h:Hospital {id: $hid})
                OPTIONAL MATCH (d)-[:SPECIALIZES_IN]->(s:Specialization)
                RETURN d.sql_id AS sql_id, d.name AS name, d.designation AS designation,
                       collect(DISTINCT s.name) AS specializations
                ORDER BY d.name
                LIMIT $limit
                """,
                hid=hospital_id, limit=limit,
            )
            return await result.data()


async def get_loader() -> Neo4jLoader:
    return Neo4jLoader(
        settings.neo4j_uri,
        settings.neo4j_username,
        settings.neo4j_password,
        settings.neo4j_database,
    )
