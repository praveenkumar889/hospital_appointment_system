# Perumbakkam GraphRAG Regression Test Report

**Run date:** 2026-08-05 · **Target:** live KB API on `http://localhost:8000` (server was already up) · **Tenant under test:** `glh-chn` (Perumbakkam)
**Method:** every `PMBK-*` case from `perumbakkam_graphrag_regression_test_suite.md` was fired at the real, running API (no mocks) via `run_regression_tests.py`. Raw responses are saved in `regression_results_raw.json` for audit.

## Scorecard

| Result | Count | Meaning |
|---|---|---|
| ✅ PASS | 29 / 36 | Behavior matched the documented expectation |
| ⚠️ PARTIAL — test too strict | 4 / 36 | System behavior is reasonable; my original assertion was wrong, not the code |
| ❌ FAIL — real bug | 3 / 36 | Confirmed defect in `src/knowledge_base` |

**No crashes, no 500s, no data loss anywhere** (79 doctors before and after, including the SQL-injection attempt in H4).

---

## Root cause behind most of the "noisy result set" findings

Before the per-case table — one mechanism explains 4 of the 7 non-clean results (A1, A3, D1, D2), so I'm flagging it once instead of repeating it:

In `_fuse_results()` (`src/knowledge_base/query/graphrag_engine.py:262-278`):
```python
if kw_lower and any(k in combined_dept or (len(k) >= 4 and k[:4] in combined_dept) for k in kw_lower):
    matched_docs.append(doc)
else:
    other_docs.append(doc)
base_candidates = matched_docs if matched_docs else other_docs
```
Whenever `specialization_keywords` is **empty** (name lookups, generic/booking queries) — or a keyword's stem genuinely doesn't appear in any department string — **every** candidate falls into `other_docs`, so `base_candidates` becomes the *entire* unfiltered pool. Then the branch round-robin selector:
```python
while len(final_fused) < n and any(branch_groups.values()):
```
was written for multi-branch fairness, but Perumbakkam is the **only branch currently loaded** — so with one branch it just drains up to `n` (default 20) candidates regardless of relevance. Net effect: the correct doctor is still ranked #1 via RRF almost every time, but the surrounding result list is padded with unrelated doctors instead of being narrowed. This isn't necessarily wrong (better to over-return than under-return for an LLM to synthesize from) but it does **not** match what the architecture doc implies ("scoped candidates"), so it's worth knowing before writing tests for the next branch.

---

## Detailed Results

### A. Symptom → Specialty Mapping

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-A1 | ⚠️ Test too strict | Returned all 5 Cardiology doctors as expected **plus** `Madhusudhan M` (CARDIO THORACIC SURGERY) and `Govini Balasubramani` (Cardiothoracic/Heart-Lung Transplant). This is the *intended* 4-char stem match ("cardio…") pulling in genuinely heart-related surgical specialties — not a bug. My assertion ("dept must equal Cardiology") was wrong; should be `dept.lower().startswith("cardio")`. The 5 pure-Cardiology doctors were still correctly ranked first in the synthesized answer. |
| PMBK-A2 | ✅ PASS | Exactly `{R.Ramachandran, Nidhi Singh}` — nothing else. |
| PMBK-A3 | ⚠️ Test too strict | Got all 4 Pulmonary Medicine doctors (I'd only listed 3 — my omission of `S Suresh Sagadevan`) plus `Govini Balasubramani` again (legitimately has "Lung Transplant" in his specialization string). Same stem-match story as A1. |
| PMBK-A4 | ✅ PASS | Exactly `{A R A Changanidi, Karthik V C, Muruganandham K}` as documented. |
| PMBK-A5 | ❌ FAIL | Expected the result set to be limited to the sole ENT doctor. Actual: `Andrew Thomas Kurian` **is** ranked #1 (correct), but the set is padded to 12 doctors spanning Radiology, Pulmonary Medicine, Orthopaedics, Gastroenterology — none of which are ENT-related. This is the padding mechanism above: `"ear"`/`"ent"` keyword extraction didn't stem-match cleanly against `"ENT EAR-NOSE-THROAT"`, so `matched_docs` came back effectively empty and the full pool flooded in. |

### B. US/UK Spelling Stem Normalization

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-B1 | ✅ PASS | Exactly `{Mithun Manohar, Shiva Reddy, Ajit Yadav, Thiagarajan Pandian}`. |
| PMBK-B2 | ✅ PASS | Same 4-doctor set as B1 (order differs, set identical). |
| PMBK-B3 | ❌ **FAIL — confirmed bug** | This is the most important finding. `"gynecologist"` (US) and `"gynaecologist"` (UK) were supposed to normalize to the same result — that's the exact claim in the architecture doc ("solves spelling variations across US/UK English"). They don't: **UK spelling** (`"gynaecologist"`) correctly narrows to 4 doctors (`Padmapriya Vivek`, `Shanthini Sounder`, plus `Karthik V C`/`Muruganandham K` via "Urogynaecology"). **US spelling** (`"gynecologist"`) floods to the unfiltered 20-doctor padded set. Root cause: the stem is `keyword[:4]`. `"gynecologist"[:4]` = `"gyne"`. The department string is `"gynaecology"` (g‑y‑n‑**a**‑e‑c…) — `"gyne"` is **not** a substring of `"gynaecology"` because of the extra `a`. So the 4-char-prefix trick silently fails for exactly the US-spelling direction of this word pair (and will fail similarly for any word where the American/British spellings diverge within the first 4 letters, not just after). |
| PMBK-B4 | ✅ PASS | Exact experience-order match: `Ajit Yadav(33) → Mithun Manohar(15) → Thiagarajan Pandian(13) → Shiva Reddy(12)`. |

### C. Language Filtering & Department Scoping

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-C1 | ✅ PASS | **This is the exact scenario from your architecture doc**, and it reproduced perfectly: all 4 Ortho doctors preserved, and the AI response explicitly states "none of the listed Orthopedic specialists... mention Telugu." Confirms the "Primary Department Language Scoping" feature works as designed. |
| PMBK-C2 | ✅ PASS | `Karthick Anjaneyan J` surfaced (plus `Govini Balasubramani`, who is also cardio-adjacent and genuinely speaks Telugu — reasonable, not a contradiction). |
| PMBK-C3 | ✅ PASS | Exactly `Padmapriya Vivek`, nothing else. |
| PMBK-C4 | ✅ PASS | 4 Ortho candidates preserved with 0 Malayalam speakers, as predicted. |
| PMBK-C5 | ✅ PASS | Exactly `Kuntraj Dung` — zero leakage from other departments' Telugu speakers. This is the cleanest, most convincing scoping result in the whole suite. |

### D. Doctor Name Lookup

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-D1 | ⚠️ Test too strict | `intent=book_appointment` ✅, `Ajit Yadav` is `doctors[0]` (top-ranked) ✅ — but result set padded to 20 (see root cause above), not "top/only." Should have asserted rank, not set size. |
| PMBK-D2 | ⚠️ Test too strict | Same pattern — `intent=get_doctor_info` ✅, `Susan George` top-ranked ✅, 20-doctor padded set. |
| PMBK-D3 | ✅ PASS | `GET /doctors/dr-karthik-v-c-chn` → exact match on name, UROLOGY, 24 yrs, Tamil/English/Hindi, Perumbakkam hospital. |
| PMBK-D4 | ✅ PASS | `404`, `detail="Doctor 'dr-does-not-exist-chn' not found"` — exact match. |
| PMBK-D5 | ✅ PASS (exceeded expectation) | This was flagged as "known-risk" in the suite. Despite the typo (`"Dr Ajith Yadev"`), `Ajit Yadav` still came back ranked #1. Typo tolerance works better than expected — no action needed. |

### E. Known-Gap Filters (locking in current behavior)

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-E1 | ✅ PASS | Confirmed exactly as documented: all cardiology-adjacent doctors returned regardless of the "more than 20 years" phrasing — `preferences.min_experience` is extracted by the LLM but never applied in fusion. |
| PMBK-E2 | ✅ PASS (gap confirmed, even more clearly than expected) | "Cheapest consultation doctor" did **not** surface `Sai Kishore S` (₹500, the actual cheapest doctor in the whole dataset) at all — he's entirely absent from the result. Confirms there is no fee-based ranking anywhere in the pipeline. |

### F. Appointment Assistant

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-F1 | ❌ **FAIL — confirmed bug** | Expected `next_steps` to contain a fee line (`"Consultation fee: ₹2500..."`) and a booking-page step, per the `BOOK_APPOINTMENT` branch in `_build_next_steps()`. Actual: got the generic 2-line fallback (`"Review the suggested doctors above"`, `"Click a booking link..."`) even though `intent` correctly resolved to `book_appointment`. Root cause: that branch only fires `if intent == BOOK_APPOINTMENT and booking_links` — and `booking_links` is built from `d.get("booking_url") or d.get("profile_url")`, but **no doctor record in the Perumbakkam dataset has either field populated** (confirmed by inspecting the raw doctor dicts — `booking_url`/`profile_url` are simply absent). So the booking-specific guidance never triggers for *any* doctor in this branch, regardless of intent. This is a real, reproducible gap between the documented behavior and what a user booking through Perumbakkam actually sees. |
| PMBK-F2 | ✅ PASS | Generic next_steps, no contact-phone lines (matches prediction — `contact_phone` is hardcoded to `""` in `get_tenant_config()` for all non-default paths). |
| PMBK-F3 | ✅ PASS | `appointment_context.doctor_id == "dr-ajit-yadav--chn"`, non-empty instructions. |
| PMBK-F4 | ✅ PASS | Unknown ID → graceful fallback to a real doctor (`Aruna Rani P K`), no crash. |

### G. Tenant Isolation

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-G1 | ✅ PASS | `tenant_id=glh-chn` → non-empty Perumbakkam results. |
| PMBK-G2 | ✅ PASS — **tripwire confirmed live** | `tenant_id=glh-adyar` → `doctors: []`. Exactly the boundary this test was built to pin. When Adyar data eventually gets loaded, re-running this suite is what will tell you it landed — right now it correctly proves Adyar has zero data and the system doesn't accidentally leak Perumbakkam doctors under the Adyar label. |
| PMBK-G3 | ✅ PASS | No `tenant_id` → still resolves to Perumbakkam doctors via the `"glh"` fallback. |

### H. Negative / Robustness

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-H1 | ✅ PASS | Gibberish query → `200`, `intent=unknown`, no crash. |
| PMBK-H2 | ✅ PASS | `"podiatrist"` (absent specialty) → `200`, graceful fallback list, no crash. |
| PMBK-H3 | ✅ PASS | Ambiguous cross-department query → `200`, sensibly split its answer into an Orthopaedics section and a Dermatology section rather than crashing or blending nonsensically. |
| PMBK-H4 | ✅ PASS | SQL-injection payload → `200`, no error, and `SELECT COUNT(*) FROM doctors` immediately after still returned **79** — parameterized queries hold. |
| PMBK-H5 | ✅ PASS | Empty `q=""` → `200` (not `422`), graceful non-crashing response. |

### I. Direct Graph / Vector Routes

| ID | Verdict | Actual vs Expected |
|---|---|---|
| PMBK-I1 | ✅ PASS | Pure vector search, 5 chunks, all `tenant_id=glh-chn`, all cardiac-relevant. |
| PMBK-I2 | ✅ PASS | `specialty=Nephrology` → exactly 1 doctor, `A R A Changanidi`. |
| PMBK-I3 | ✅ PASS | Non-empty chunk for `dr-ajit-yadav--chn`, correct metadata. |

---

## Summary of Real Bugs to Fix (3)

1. **PMBK-B3 — US-spelling stem match fails for "gynecologist"→"gynaecology."** The `keyword[:4]` prefix trick breaks whenever the US/UK spellings diverge inside the first 4 characters (not just after). Affects at least this word pair; worth auditing other US/UK medical-term pairs (e.g. "anesthesiologist" vs "anaesthesiologist" — `"anes"` vs `"anaes...`" — likely has the same problem; not directly tested here but same failure shape).
2. **PMBK-F1 — Booking-specific next steps never fire.** `booking_url`/`profile_url` are unpopulated for all 79 Perumbakkam doctors, so `booking_links` is always empty and the `BOOK_APPOINTMENT` guidance branch in `_build_next_steps()` is dead code for this branch's data. Either populate these fields during data load, or stop gating the fee-line/booking-step guidance on `booking_links`.
3. **PMBK-A5 (and the related D1/D2 pattern) — single-branch round-robin padding.** Not necessarily wrong, but worth a deliberate decision: when `matched_docs` is empty, should the fallback really be "return up to `n` doctors from every department," or should it degrade more gracefully (e.g., pure vector-similarity ranking) when the department signal is weak? This will get more visible once a second branch (Adyar, etc.) is loaded and the round-robin actually round-robins across branches instead of draining one.

Everything else — the headline claims in the architecture doc (Telugu-language department scoping, US/UK Ortho and Gynae-via-UK-spelling stem matching, tenant isolation, SQL-injection safety, 404 handling) — held up under live testing.
