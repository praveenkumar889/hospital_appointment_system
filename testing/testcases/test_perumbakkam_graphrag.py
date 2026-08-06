"""
Perumbakkam Branch GraphRAG Regression Suite — src/knowledge_base (tenant `glh-chn`)

The single source of truth for GraphRAG regression testing. Run with:
    pytest testing/testcases/test_perumbakkam_graphrag.py -v

Requires the KB API running locally (default http://localhost:8000, override with
KB_API_URL) and the SQLite DB at src/workflows/data/db/knowledge_base.db (override
with KB_DB_PATH). Requests can be slow (Azure OpenAI intent classification +
response synthesis on every /search/doctors call) — default timeout is 60s.

Tests marked `xfail(strict=True)` are CONFIRMED BUGS, not flaky tests. They encode
the behavior the system *should* have; they will start failing loudly (XPASS) the
day someone fixes the underlying issue in src/knowledge_base, which is the signal
to remove the marker. See each docstring for the root cause.

Scope: Perumbakkam (`glh-chn`) is the only branch with data loaded today. This file
covers src/knowledge_base only — src/agent and src/workflows are separate systems
and out of scope here.
"""
from __future__ import annotations

import os
import sqlite3

import pytest
import requests

BASE_URL = os.environ.get("KB_API_URL", "http://localhost:8000")
DB_PATH = os.environ.get("KB_DB_PATH", "src/workflows/data/db/knowledge_base.db")
TIMEOUT = 60


# ── helpers ──────────────────────────────────────────────────────────────────

def search(q, n=20, tenant_id=None, timeout=TIMEOUT):
    params = {"q": q, "n": n}
    if tenant_id is not None:
        params["tenant_id"] = tenant_id
    return requests.get(f"{BASE_URL}/search/doctors", params=params, timeout=timeout)


def search_no_q(n=20, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/search/doctors", params={"n": n}, timeout=timeout)


def get_doctor(doctor_id, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/doctors/{doctor_id}", timeout=timeout)


def get_chunks(doctor_id, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/doctors/{doctor_id}/chunks", timeout=timeout)


def by_specialty(specialty, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/search/doctors/by-specialty", params={"specialty": specialty}, timeout=timeout)


def semantic(q, n=5, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/search/doctors/semantic", params={"q": q, "n": n}, timeout=timeout)


def assist(message, timeout=TIMEOUT):
    return requests.post(f"{BASE_URL}/appointment/assist", json={"message": message}, timeout=timeout)


def quick_book(doctor_id, timeout=TIMEOUT):
    return requests.get(f"{BASE_URL}/appointment/quick-book/{doctor_id}", timeout=timeout)


def doctor_ids(resp_json):
    return {d.get("doctor_id") or d.get("id") for d in resp_json.get("doctors", [])}


def depts(resp_json):
    return {(d.get("speciality") or d.get("department") or "").upper() for d in resp_json.get("doctors", [])}


def top_id(resp_json):
    docs = resp_json.get("doctors", [])
    assert docs, "expected at least one doctor in results"
    return docs[0].get("doctor_id") or docs[0].get("id")


# ── A. Symptom -> Specialty Semantic Mapping ────────────────────────────────

def test_A1_heart_symptom_maps_to_cardiology():
    r = search("I have chest pain, need a heart doctor in Perumbakkam")
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "find_doctor"
    assert all(d.startswith("CARDIO") or "HEART" in d for d in depts(body))
    assert {"dr-susan-george--chn", "dr-gobu-p-chn", "dr-guru-prasad-s-chn",
            "dr-karthick-anjaneyan-j-chn", "dr-v-k-sanjeev--chn"} & doctor_ids(body)


def test_A2_skin_symptom_maps_to_dermatology_exact():
    r = search("skin doctor for acne")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {"dr-r-ramachandran--chn", "dr-nidhi-singh--chn"}


def test_A3_breathing_symptom_maps_to_pulmonology():
    r = search("breathing difficulty, need a lung doctor")
    assert r.status_code == 200
    body = r.json()
    assert "dr-sreenivasan-v-chn" in doctor_ids(body)
    assert all("PULMON" in d or "LUNG" in d for d in depts(body))


def test_A4_kidney_specialist_exact():
    r = search("kidney specialist")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    assert ids == {"dr-a-r-a-changanidi-chn", "dr-karthik-v-c-chn", "dr-muruganandham-k-chn"}


def test_A5_ent_doctor_top_ranked():
    """Sole ENT doctor (Andrew Thomas Kurian) is top-ranked even though the low-signal
    'ear'/'ent' keyword doesn't stem-match cleanly and pads the rest of the list with
    unrelated departments (see module docstring re: single-branch padding)."""
    r = search("ear pain, need an ENT doctor")
    assert r.status_code == 200
    assert top_id(r.json()) == "dr-andrew-thomas-kurian-chn"


# ── B. US/UK Spelling Stem Normalization ────────────────────────────────────

ORTHO_SET = {"dr-mithun-manohar-chn", "dr-shiva-reddy--chn", "dr-ajit-yadav--chn", "dr-thiagarajan-pandian--chn"}


def test_B1_us_orthopedic_exact():
    r = search("orthopedic doctor")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == ORTHO_SET


def test_B2_uk_orthopaedic_matches_B1():
    r = search("orthopaedic surgeon")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == ORTHO_SET


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED BUG: keyword[:4]='gyne' is not a substring of 'gynaecology' (g-y-n-A-e-c...), "
    "so the US spelling 'gynecologist' fails the department stem match entirely and falls back "
    "to the unfiltered ~20-doctor pool instead of isolating the 2 real OBGYN doctors. "
    "UK spelling 'gynaecologist' (see test_B3b) narrows correctly."
))
def test_B3a_us_gynecologist_should_narrow():
    r = search("gynecologist")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {"dr-padmapriya-vivek-chn", "dr-shanthini-sounder-chn"}


def test_B3b_uk_gynaecologist_narrows():
    r = search("gynaecologist")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    assert {"dr-padmapriya-vivek-chn", "dr-shanthini-sounder-chn"} <= ids
    assert len(ids) <= 4  # OBGYN pair + Urology's "Urogynaecology" cross-match, no broad padding


def test_B4_by_specialty_orthopaedics_experience_order():
    r = by_specialty("Orthopaedics")
    assert r.status_code == 200
    ordered_ids = [d["sql_id"] for d in r.json()["doctors"]]
    assert ordered_ids == ["dr-ajit-yadav--chn", "dr-mithun-manohar-chn",
                            "dr-thiagarajan-pandian--chn", "dr-shiva-reddy--chn"]


# ── C. Language Filtering & Primary-Department Scoping ──────────────────────

def test_C1_orthopedic_telugu_scoping_preserved():
    """Architecture-doc reference scenario: 0 of 4 Ortho doctors speak Telugu ->
    fusion must preserve the department candidates rather than return nothing."""
    r = search("Find me an Orthopedic doctor in Chennai who speaks Telugu")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == ORTHO_SET


def test_C2_cardiologist_telugu_narrows():
    r = search("Cardiologist who speaks Telugu")
    assert r.status_code == 200
    body = r.json()
    assert "dr-karthick-anjaneyan-j-chn" in doctor_ids(body)
    assert all(d.startswith("CARDIO") or "HEART" in d for d in depts(body))


def test_C3_gynaecologist_telugu_exact():
    r = search("Gynaecologist speaking Telugu")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {"dr-padmapriya-vivek-chn"}


def test_C4_orthopaedic_malayalam_scoping_preserved():
    r = search("orthopaedic doctor who speaks Malayalam")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == ORTHO_SET


def test_C5_anaesthesiologist_telugu_exact_no_leakage():
    r = search("Anaesthesiologist who speaks Telugu")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {"dr-kuntraj-dung-chn"}


# ── D. Doctor Name Lookup ────────────────────────────────────────────────────

def test_D1_book_named_doctor_intent_and_top_rank():
    r = search("Book appointment with Dr. Ajit Yadav")
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "book_appointment"
    assert top_id(body) == "dr-ajit-yadav--chn"


def test_D2_get_info_named_doctor_intent_and_top_rank():
    r = search("Tell me about Dr Susan George")
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "get_doctor_info"
    assert top_id(body) == "dr-susan-george--chn"


def test_D3_direct_profile_fetch():
    r = get_doctor("dr-karthik-v-c-chn")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Karthik V C"
    assert body["experience_years"] == 24
    assert any("UROLOGY" in s.upper() for s in body["specializations"])
    assert set(body["languages"]) >= {"Tamil", "English", "Hindi"}


def test_D4_unknown_doctor_404():
    r = get_doctor("dr-does-not-exist-chn")
    assert r.status_code == 404
    assert r.json()["detail"] == "Doctor 'dr-does-not-exist-chn' not found"


def test_D5_misspelled_name_still_top_ranked():
    """Typo tolerance exceeded expectations in the first run: despite 'Ajith Yadev'
    instead of 'Ajit Yadav', the correct doctor still ranked #1."""
    r = search("Dr Ajith Yadev")
    assert r.status_code == 200
    assert top_id(r.json()) == "dr-ajit-yadav--chn"


# ── E. Known-Gap Filters (lock in current, likely-unintended behavior) ──────

def test_E1_experience_preference_not_enforced():
    r = search("Cardiologist with more than 20 years experience")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    all_cardiology = {"dr-susan-george--chn", "dr-gobu-p-chn", "dr-guru-prasad-s-chn",
                       "dr-karthick-anjaneyan-j-chn", "dr-v-k-sanjeev--chn"}
    assert all_cardiology <= ids, "min_experience preference is extracted but never applied in _fuse_results()"


def test_E2_no_fee_based_ranking():
    r = search("Cheapest consultation doctor")
    assert r.status_code == 200
    body = r.json()
    assert body["doctors"], "call should still succeed with a non-empty list"
    assert "dr-sai-kishore-s--chn" not in doctor_ids(body), (
        "no fee-sort exists anywhere in the pipeline -- the actual cheapest doctor "
        "(Sai Kishore S, Rs.500) is not even surfaced"
    )


# ── F. Appointment Assistant ─────────────────────────────────────────────────

def test_F1_book_intent_suggests_correct_doctor():
    r = assist("I want to book an appointment with Dr. Ajit Yadav")
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "book_appointment"
    assert body["suggested_doctors"][0]["doctor_id"] == "dr-ajit-yadav--chn"


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED BUG: no doctor record in the Perumbakkam dataset has booking_url or "
    "profile_url populated, so booking_links is always [] regardless of intent, so "
    "the BOOK_APPOINTMENT-specific next_steps branch in _build_next_steps() "
    "(fee line + booking-page step) is dead code for this branch's data."
))
def test_F1_book_intent_next_steps_include_fee_line():
    r = assist("I want to book an appointment with Dr. Ajit Yadav")
    assert r.status_code == 200
    next_steps_text = " ".join(r.json()["next_steps"])
    assert "2500" in next_steps_text


def test_F2_find_intent_generic_next_steps():
    r = assist("Find a cardiologist")
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "find_doctor"
    assert body["next_steps"] == [
        "Review the suggested doctors above",
        "Click a booking link to schedule your appointment",
    ]


def test_F3_quick_book_known_doctor():
    r = quick_book("dr-ajit-yadav--chn")
    assert r.status_code == 200
    assert r.json()["appointment_context"]["doctor_id"] == "dr-ajit-yadav--chn"


def test_F4_quick_book_unknown_doctor_graceful_fallback():
    r = quick_book("dr-nobody-chn")
    assert r.status_code == 200
    assert "appointment_context" in r.json()


# ── G. Tenant Isolation ──────────────────────────────────────────────────────

def test_G1_explicit_perumbakkam_tenant_nonempty():
    r = search("cardiologist", tenant_id="glh-chn")
    assert r.status_code == 200
    assert r.json()["doctors"]


def test_G2_unloaded_sibling_tenant_returns_empty():
    """Tripwire: glh-adyar has zero doctors loaded today. Once its data lands, this
    test will start failing -- that failure IS the signal the data has arrived, at
    which point this test should be replaced with real Adyar assertions."""
    r = search("cardiologist", tenant_id="glh-adyar")
    assert r.status_code == 200
    assert r.json()["doctors"] == []


def test_G3_no_tenant_defaults_to_perumbakkam():
    r = search("cardiologist")
    assert r.status_code == 200
    assert r.json()["doctors"]


# ── H. Negative / Robustness ─────────────────────────────────────────────────

def test_H1_gibberish_query_no_crash():
    r = search("asdkjaskjd123")
    assert r.status_code == 200


def test_H2_absent_specialty_no_crash():
    r = search("podiatrist")
    assert r.status_code == 200


def test_H3_ambiguous_cross_department_no_crash():
    r = search("orthopedic dermatologist")
    assert r.status_code == 200


def test_H4_sql_injection_safe():
    r = search("'; DROP TABLE doctors; --")
    assert r.status_code == 200
    conn = sqlite3.connect(DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    finally:
        conn.close()
    assert count == 79


def test_H5_empty_query_no_422():
    r = search("")
    assert r.status_code == 200


# ── I. Direct Graph / Vector Routes ──────────────────────────────────────────

def test_I1_pure_vector_search():
    r = semantic("heart specialist", n=5)
    assert r.status_code == 200
    results = r.json()["results"]
    assert 0 < len(results) <= 5
    assert all(res["metadata"]["tenant_id"] == "glh-chn" for res in results)


def test_I2_by_specialty_nephrology_exact():
    r = by_specialty("Nephrology")
    assert r.status_code == 200
    doctors = r.json()["doctors"]
    assert len(doctors) == 1
    assert doctors[0]["sql_id"] == "dr-a-r-a-changanidi-chn"


def test_I3_doctor_chunks_nonempty():
    r = get_chunks("dr-ajit-yadav--chn")
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"]
    assert body["chunks"][0]["metadata"]["doctor_id"] == "dr-ajit-yadav--chn"


# ── J. Generalizing the Stem-Mismatch Bug (US/UK word pairs) ────────────────

@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED BUG (most severe in the suite): 'anesthesiologist'[:4]='anes' is not a "
    "substring of 'anaesthesiology', so ZERO of the 6 real Anaesthesiology doctors "
    "appear anywhere in the results -- the correct department is fully erased, not "
    "just diluted. UK spelling 'anaesthesiologist' (test_J2) surfaces all 6 correctly."
))
def test_J1_us_anesthesiologist_should_include_dept():
    r = search("anesthesiologist for surgery")
    assert r.status_code == 200
    assert "ANAESTHESIOLOGY" in depts(r.json())


def test_J2_uk_anaesthesiologist_includes_all_six():
    r = search("anaesthesiologist for surgery")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    all_anaesthesiology = {"dr-selvakumar-k-chn", "dr-padmini-c-r-chn", "dr-madurima-s-chn",
                            "dr-ellango-a-p-chn", "dr-kuntraj-dung-chn", "dr-selvakumar-malleeswaran-chn"}
    assert all_anaesthesiology <= ids


def test_J3_us_pediatrician_includes_all_three():
    r = search("pediatrician for my child")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    assert {"dr-mohan-babu-kasala-chn", "dr-karnan-p-chn", "dr-aruna-rani-p-k--chn"} <= ids


def test_J4_uk_paediatrician_exact_family():
    r = search("paediatrician for my child")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {
        "dr-mohan-babu-kasala-chn", "dr-karnan-p-chn", "dr-aruna-rani-p-k--chn",
        "dr-shreela-sherine-pauliah-chn", "dr-ponni-sivaprakasam--chn", "dr-k-lakshmi-narayanan--chn",
    }


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED BUG, mirror direction of J1/B3a: PAEDIATRIC HEMATO ONCOLOGY is stored "
    "US-spelled in this dataset, so the UK-spelled query 'haemato'[:4]='haem' fails to "
    "match it and the single correct doctor isn't isolated (though she still ranks #1)."
))
def test_J5_uk_haemato_against_us_spelled_dept_should_isolate():
    r = search("haemato oncologist for child cancer")
    assert r.status_code == 200
    assert doctor_ids(r.json()) == {"dr-ponni-sivaprakasam--chn"}


# ── K. City Scoping ──────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED BUG: querying a city with zero doctors (Mumbai) returns the identical "
    "7-doctor Chennai result set as a correct Chennai query, with no structured signal "
    "of the mismatch -- only the free-text ai_response hedges. ChromaDB's vector leg "
    "has no city filter at all, so it backfills the same doctors via RRF regardless of "
    "what Neo4j's city-scoped graph leg returns."
))
def test_K1_city_with_zero_doctors_should_be_empty():
    r = search("cardiologist in Mumbai")
    assert r.status_code == 200
    assert r.json()["doctors"] == []


def test_K2_correct_city_control_case():
    r = search("cardiologist in Chennai")
    assert r.status_code == 200
    assert r.json()["doctors"]


# ── L. API Parameter Validation ──────────────────────────────────────────────

def test_L1_n_above_max_422():
    r = search("cardiologist", n=100)
    assert r.status_code == 422


def test_L2_n_below_min_422():
    r = search("cardiologist", n=0)
    assert r.status_code == 422


def test_L3_missing_q_422():
    r = search_no_q()
    assert r.status_code == 422


# ── M. Determinism ────────────────────────────────────────────────────────────

def test_M1_repeated_query_same_doctor_set():
    r1 = search("Cardiologist who speaks Telugu")
    r2 = search("Cardiologist who speaks Telugu")
    assert r1.status_code == 200 and r2.status_code == 200
    assert doctor_ids(r1.json()) == doctor_ids(r2.json())


# ── N. Designation-Based Fulltext Search ─────────────────────────────────────

def test_N1_hod_query_surfaces_real_hod_doctors():
    r = search("Who is the HOD?")
    assert r.status_code == 200
    ids = doctor_ids(r.json())
    known_hods = {"dr-madurima-s-chn", "dr-rajavel-v-p-chn", "dr-praveen-chander--chn", "dr-mahadevan-b-chn"}
    assert known_hods & ids, "at least some genuine HOD-designation doctors should surface"
