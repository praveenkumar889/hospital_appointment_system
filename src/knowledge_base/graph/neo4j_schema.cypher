// ============================================================
// Neo4j Schema for Doctor Appointment Knowledge Graph
// Run once on a fresh Neo4j instance to set up constraints & indexes
// ============================================================

// ---------- Constraints (enforce uniqueness + create indexes) ----------

CREATE CONSTRAINT doctor_id_unique IF NOT EXISTS
FOR (d:Doctor) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT hospital_id_unique IF NOT EXISTS
FOR (h:Hospital) REQUIRE h.id IS UNIQUE;

CREATE CONSTRAINT specialization_name_unique IF NOT EXISTS
FOR (s:Specialization) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT qualification_degree_unique IF NOT EXISTS
FOR (q:Qualification) REQUIRE q.degree IS UNIQUE;

CREATE CONSTRAINT language_name_unique IF NOT EXISTS
FOR (l:Language) REQUIRE l.name IS UNIQUE;

// ---------- Full-text search indexes ----------

CREATE FULLTEXT INDEX doctor_search IF NOT EXISTS
FOR (d:Doctor) ON EACH [d.name, d.bio, d.designation];

CREATE FULLTEXT INDEX specialization_search IF NOT EXISTS
FOR (s:Specialization) ON EACH [s.name, s.category];

// ---------- Property indexes for fast lookups ----------

CREATE INDEX doctor_name IF NOT EXISTS FOR (d:Doctor) ON (d.name);
CREATE INDEX doctor_exp IF NOT EXISTS FOR (d:Doctor) ON (d.experience_years);
CREATE INDEX hospital_city IF NOT EXISTS FOR (h:Hospital) ON (h.city);
CREATE INDEX hospital_location IF NOT EXISTS FOR (h:Hospital) ON (h.location);
