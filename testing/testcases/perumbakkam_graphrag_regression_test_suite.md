# Perumbakkam Branch — `src/knowledge_base` GraphRAG Regression Test Suite

Scope: **`src/knowledge_base/` only** (tenant `glh-chn` = Gleneagles HealthCity, Perumbakkam‑Sholinganallur, Chennai).
This is the **only branch currently loaded** in `knowledge_base.db` / Neo4j / ChromaDB (79 doctors, 1 hospital row, `location_id=80`). Other branches (`glh-adyar`, `glh-kengeri`, `glh-richmond`, `glh-parel`, `glh-lkp`, `glh-lbn`) are defined in `config.py:TENANT_META` but have **no data loaded yet** — that's the "other folders" to cover next.

---

## 1. Brief End-to-End Analysis

**What data it holds (Perumbakkam only):**
- **SQLite** (`src/workflows/data/db/knowledge_base.db`): 1 hospital row (`glh-chn`), 79 doctors across 37 specialities (Cardiology, Orthopaedics, Ortho Surgery, Dermatology, Nephrology, ENT, Pulmonary Medicine, Anaesthesiology, etc.), each with CSV `specializations`/`qualifications`/`languages`, fee, experience, designation, plus `schedule_days`/`time_slots` for 2026‑08‑04 → 2026‑08‑17 (14 slots/day/doctor).
- **Neo4j** (semantic graph only, no schedule data): `(:Doctor)-[:PRACTICES_AT]->(:Hospital)`, `(:Doctor)-[:SPECIALIZES_IN]->(:Specialization)`, `(:Doctor)-[:SPEAKS]->(:Language)`, plus fulltext indexes `doctor_ft` (name+designation) and `spec_ft` (specialization).
- **ChromaDB**: free-text embedding chunks per doctor (`all-MiniLM-L6-v2`), used for semantic/symptom-style queries.

**How it retrieves (`query/graphrag_engine.py`):**
1. `classify_intent()` (Azure OpenAI) → `find_doctor | get_doctor_info | book_appointment`, plus `specialization_keywords`, `city`, `doctor_name`, `preferences.language`.
2. `retrieve()` — parallel: ChromaDB `semantic_search()` (vector) + Neo4j `find_doctors_by_specialization` / `find_by_fulltext` (graph), tenant/city scoped.
3. `_fuse_results()` — Reciprocal Rank Fusion, then **department stem match** (`keyword[:4] in dept`) to prioritize `matched_docs`, then **language filter scoped to the matched department only** (preserves department candidates if 0 speak the requested language), then multi-branch round-robin cap to `n`.
4. `_enrich_from_sqlite()` — joins back to SQLite for qualifications/fee/designation/branch name.
5. `synthesize_response()` (Azure OpenAI) builds the final natural-language answer + `booking_links`.

Exposed routes: `GET /search/doctors`, `GET /search/doctors/semantic`, `GET /search/doctors/by-specialty`, `GET /doctors/{id}`, `GET /doctors/{id}/chunks`, `POST /appointment/assist`, `GET /appointment/quick-book/{id}`.

⚠️ Note: `preferences.min_experience` / fee preferences are **extracted** by the LLM but **never applied** in `_fuse_results()` — only `preferences.language` is enforced. Tests E1/E2 below lock in this current (likely unintended) behavior.

---

## 2. Regression Test Cases

Legend — **Endpoint**: KB route exercised · **Basis**: verified directly against live `knowledge_base.db` on 2026‑08‑05.

### A. Symptom → Specialty Semantic Mapping (ChromaDB vector search)

| ID | Scenario | Endpoint | Input (`q`) | Expected Output |
|---|---|---|---|---|
| PMBK-A1 | Symptom phrase maps to Cardiology | `GET /search/doctors` | `"I have chest pain, need a heart doctor in Perumbakkam"` | `intent=find_doctor`. All returned doctors' `speciality`/`department` = Cardiology. Must include ≥1 of: Susan George, Gobu P, Guru Prasad S, Karthick Anjaneyan J, V K Sanjeev. No Orthopaedics/Dermatology doctors in results. |
| PMBK-A2 | Symptom phrase maps to Dermatology | `GET /search/doctors` | `"skin doctor for acne"` | Results limited to Dermatology: R.Ramachandran, Nidhi Singh (only 2 doctors exist in this dept — result set ⊆ these 2). |
| PMBK-A3 | Symptom phrase maps to Pulmonology | `GET /search/doctors` | `"breathing difficulty, need a lung doctor"` | Results limited to Pulmonary Medicine: Sreenivasan V, Sindhura Koganti, Vimi Varghese. |
| PMBK-A4 | Single-doctor department still resolves | `GET /search/doctors` | `"kidney specialist"` | Nephrology → must return `A R A Changanidi` (sole doctor in dept, 11 yrs, Tamil/English/Hindi/Kannada, ₹800). |
| PMBK-A5 | Single-doctor department (ENT) | `GET /search/doctors` | `"ear pain, need an ENT doctor"` | ENT EAR-NOSE-THROAT → must return `Andrew Thomas Kurian` (sole doctor, 15 yrs, ₹1500). |

### B. US/UK Spelling Stem Normalization (`k[:4] in combined_dept`)

| ID | Scenario | Endpoint | Input (`q`) | Expected Output |
|---|---|---|---|---|
| PMBK-B1 | US spelling "orthopedic" | `GET /search/doctors` | `"orthopedic doctor"` | Stem `orth` matches both `ORTHOPAEDICS` and `ORTHO SURGERY` depts → result set = {Shiva Reddy, Ajit Yadav, Mithun Manohar, Thiagarajan Pandian} (4 doctors, order may vary). |
| PMBK-B2 | UK spelling "orthopaedic" — must match B1 exactly | `GET /search/doctors` | `"orthopaedic surgeon"` | Same 4-doctor set as PMBK-B1. Regression: B1 result set == B2 result set. |
| PMBK-B3 | US "gynecologist" vs UK "gynaecologist" | `GET /search/doctors` (×2 calls) | `"gynecologist"` then `"gynaecologist"` | Both calls → `{Padmapriya Vivek, Shanthini Sounder}` (OBSTETRICS & GYNAECOLOGY, only 2 doctors in dept). Identical set both times. |
| PMBK-B4 | Neo4j-only stem check via graph route | `GET /search/doctors/by-specialty?specialty=Orthopaedics` | — | Cypher root-match (`ortho*`) ordered `experience_years DESC` → exact order: Ajit Yadav(33), Mithun Manohar(15), Thiagarajan Pandian(13), Shiva Reddy(12). |

### C. Language Filtering & Primary-Department Scoping

| ID | Scenario | Endpoint | Input (`q`) | Expected Output |
|---|---|---|---|---|
| PMBK-C1 | **Architecture-doc reference case** — 0 doctors in dept speak requested language | `GET /search/doctors` | `"Find me an Orthopedic doctor in Chennai who speaks Telugu"` | 0 of {Shiva Reddy, Ajit Yadav, Mithun Manohar, Thiagarajan Pandian} speak Telugu → fusion must **preserve** the Ortho candidates (not return empty / unrelated dept), and `ai_response` should note Telugu is not available among Orthopaedic doctors while still listing them. |
| PMBK-C2 | Language filter narrows to exact match (1 of 5) | `GET /search/doctors` | `"Cardiologist who speaks Telugu"` | Must surface `Karthick Anjaneyan J` (only Telugu-speaking Cardiology doctor); other 4 cardiologists deprioritized/excluded. |
| PMBK-C3 | Language filter narrows within small dept | `GET /search/doctors` | `"Gynaecologist speaking Telugu"` | Must surface `Padmapriya Vivek` (Tamil/English/Telugu); `Shanthini Sounder` (no Telugu) deprioritized. |
| PMBK-C4 | Requested language present nowhere in dept (regression twin of C1, different language) | `GET /search/doctors` | `"orthopaedic doctor who speaks Malayalam"` | 0 Malayalam speakers exist in Ortho depts (only Manikandan Kathirvel/Liver-Transplant and Vimi Varghese/Pulmonology speak Malayalam, both outside Ortho) → preserve Ortho candidates, flag unavailability. |
| PMBK-C5 | Scoping doesn't leak language match from unrelated dept | `GET /search/doctors` | `"Anaesthesiologist who speaks Telugu"` | Anaesthesiology has 6 doctors, only `Kuntraj Dung` (43 yrs) speaks Telugu → must return him, and must NOT substitute Telugu-speaking doctors from other departments (e.g. Karthick Anjaneyan J/Cardiology) in his place. |

### D. Exact / Fuzzy Doctor Name Lookup (Neo4j `doctor_ft` fulltext)

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-D1 | Exact name → `book_appointment` intent | `GET /search/doctors` | `q="Book appointment with Dr. Ajit Yadav"` | `intent=book_appointment`; top/only result = `dr-ajit-yadav--chn` (Ortho Surgery, Senior Consultant, 33 yrs, ₹2500, Tamil/English/Hindi). |
| PMBK-D2 | Exact name → `get_doctor_info` intent | `GET /search/doctors` | `q="Tell me about Dr Susan George"` | `intent=get_doctor_info`; result = `dr-susan-george--chn` (Cardiology, 30 yrs). |
| PMBK-D3 | Direct profile fetch | `GET /doctors/dr-karthik-v-c-chn` | — | 200 OK; `name="Karthik V C"`, `speciality/specializations` contains "UROLOGY", `experience_years=24`, hospital = Perumbakkam branch, languages include Tamil/English/Hindi. |
| PMBK-D4 | Unknown doctor ID | `GET /doctors/dr-does-not-exist-chn` | — | `404`, `detail="Doctor 'dr-does-not-exist-chn' not found"`. |
| PMBK-D5 (known-risk) | Misspelled name — fuzziness tolerance | `GET /search/doctors` | `q="Dr Ajith Yadev"` | Best-effort: Lucene fulltext on `doctor_ft` is not fuzzy by default, so this **may return 0 graph hits** and fall back to vector-only/empty. Document actual behavior; not asserting a hard pass — flags a potential UX gap for typo tolerance. |

### E. Unimplemented / Known-Gap Filters (lock in current behavior)

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-E1 | `min_experience` preference extracted but not enforced | `GET /search/doctors` | `q="Cardiologist with more than 20 years experience"` | Engine does **not** filter by experience in `_fuse_results()` — expect **all 5** Cardiology doctors returned (Susan George 30, Gobu P 20, Guru Prasad S 20, Karthick Anjaneyan J 8, V K Sanjeev 8), not just the >20yr subset. If this ever starts filtering to only Susan George, it's an intentional feature change — update this test, don't treat it as a silent regression. |
| PMBK-E2 | No fee-based ranking exists | `GET /search/doctors` | `q="Cheapest consultation doctor"` | No price-sort logic in engine — result is driven purely by RRF/keyword match, not fee. Do **not** assert `Sai Kishore S` (₹500, cheapest overall) is ranked first; assert only that the call succeeds (200) and returns a non-empty list. |

### F. Appointment Assistant (`src/knowledge_base/api/routes/appointment.py`)

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-F1 | Book-intent full flow | `POST /appointment/assist` | `{"message": "I want to book an appointment with Dr. Ajit Yadav"}` | `intent="book_appointment"`; `suggested_doctors` includes Ajit Yadav; `next_steps` contains a fee line `"Consultation fee: ₹2500..."` and a booking-page step. |
| PMBK-F2 | Find-intent fallback next steps | `POST /appointment/assist` | `{"message": "Find a cardiologist"}` | `intent="find_doctor"`; `next_steps` = generic review/booking-link steps (contact-phone lines only appended if `tc.contact_phone` non-empty — currently `""` for non-default tenants, so those 2 lines should be absent). |
| PMBK-F3 | Quick-book context for known ID | `GET /appointment/quick-book/dr-ajit-yadav--chn` | — | `appointment_context.doctor_id/id == "dr-ajit-yadav--chn"`; `instructions` non-empty string. |
| PMBK-F4 | Quick-book for unknown ID doesn't crash | `GET /appointment/quick-book/dr-nobody-chn` | — | 200 OK with `appointment_context={}` or first fallback doctor (per code: falls back to `result.doctors[0]` if no exact ID match) — must not 500. |

### G. Tenant Isolation (Perumbakkam vs. not-yet-loaded branches)

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-G1 | Explicit Perumbakkam tenant | `GET /search/doctors?q=cardiologist&tenant_id=glh-chn` | — | Non-empty results, all doctors have `location_id=80` / Perumbakkam branch name. |
| PMBK-G2 | **Boundary test** — sibling branch has no data yet | `GET /search/doctors?q=cardiologist&tenant_id=glh-adyar` | — | Since `glh-adyar` has 0 doctors currently loaded, expect an empty (or near-empty, graceful) result — **not** a 500, and **not** silently returning Perumbakkam doctors mislabeled as Adyar. This is the exact seam the "other folders" work will fill in later — pin this test now so its outcome flips visibly once Adyar data is loaded. |
| PMBK-G3 | No tenant_id → defaults through `_derive_tenant` | `GET /search/doctors?q=cardiologist` | — | `_derive_tenant(None)` → `"glh"` fallback; since `glh-chn` is the only populated tenant, results should still surface Perumbakkam doctors. |

### H. Negative / Robustness

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-H1 | Gibberish query doesn't crash | `GET /search/doctors?q=asdkjaskjd123` | — | 200 OK; `doctors` may be `[]`; no 500. |
| PMBK-H2 | Specialty absent from dataset | `GET /search/doctors?q=podiatrist` | — | 200 OK; no exact-dept match exists in the 37 Perumbakkam specialities → expect empty or broad fallback set, never a 500. |
| PMBK-H3 | Ambiguous cross-department keyword mix | `GET /search/doctors?q=orthopedic dermatologist` | — | 200 OK; fusion picks whichever keyword's `matched_docs` group is non-empty first — must not crash or return a mixed nonsensical department blend beyond documented fusion logic. |
| PMBK-H4 | SQL-injection safety (fallback path in `search.py`) | `GET /search/doctors?q='; DROP TABLE doctors; --` | — | 200 OK; parameterized `cursor.execute` in the exception-fallback path prevents injection; `SELECT COUNT(*) FROM doctors` immediately after must still return `79`. |
| PMBK-H5 | Empty query string | `GET /search/doctors?q=` | — | FastAPI/Pydantic: `q` is required (`Query(...)`) — empty string is technically valid but semantically empty; expect 200 with graceful (possibly empty) results, not a 422 (since `""` still satisfies `str` type) — confirm actual behavior. |

### I. Direct Graph / Vector Routes

| ID | Scenario | Endpoint | Input | Expected Output |
|---|---|---|---|---|
| PMBK-I1 | Pure vector search (no graph fusion) | `GET /search/doctors/semantic?q=heart specialist&n=5` | — | Returns ≤5 ChromaDB chunks; each `metadata` should reference Perumbakkam/`glh-chn` doctors (only tenant embedded). |
| PMBK-I2 | Direct graph specialty route, ordering check | `GET /search/doctors/by-specialty?specialty=Nephrology` | — | Returns exactly 1 doctor: `A R A Changanidi`. |
| PMBK-I3 | Doctor's raw vector chunks | `GET /doctors/dr-ajit-yadav--chn/chunks` | — | `chunks` non-empty list; each chunk's text/metadata references `dr-ajit-yadav--chn`. |

---

## 3. How to Run (suggested harness shape)

Each row above maps 1:1 to a `pytest` case against a running KB API (`localhost:8000`) — e.g.:

```python
def test_PMBK_C1_orthopedic_telugu_scoping(client):
    r = client.get("/search/doctors", params={"q": "Find me an Orthopedic doctor in Chennai who speaks Telugu"})
    assert r.status_code == 200
    depts = {d.get("speciality") or d.get("department") for d in r.json()["doctors"]}
    assert depts <= {"ORTHOPAEDICS", "ORTHO SURGERY"}
    assert r.json()["doctors"], "Ortho candidates must be preserved even with 0 Telugu speakers"
```

Next step once you're ready: replicate this same category structure (A–I) for `glh-adyar`, `glh-kengeri`, etc. as their data gets loaded — PMBK-G2 is the tripwire that tells you when that data has landed.
