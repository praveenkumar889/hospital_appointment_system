"""
Runs the PMBK-* regression test cases from perumbakkam_graphrag_regression_test_suite.md
against the live KB API (http://localhost:8000) and dumps raw structured results to JSON
for pass/fail analysis.
"""
import json
import sqlite3
import requests

BASE = "http://localhost:8000"
TIMEOUT = 30


def summarize_doctors(doctors):
    out = []
    for d in doctors:
        out.append({
            "id": d.get("doctor_id") or d.get("id"),
            "name": d.get("name") or d.get("doctor_name"),
            "dept": d.get("speciality") or d.get("department"),
            "specs": d.get("specializations"),
            "langs": d.get("languages"),
            "exp": d.get("experience_years"),
            "fee": d.get("consultation_fee"),
        })
    return out


def search(q, n=20, tenant_id=None, extra=None):
    params = {"q": q, "n": n}
    if tenant_id is not None:
        params["tenant_id"] = tenant_id
    if extra:
        params.update(extra)
    try:
        r = requests.get(f"{BASE}/search/doctors", params=params, timeout=TIMEOUT)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        return {"status": r.status_code, "intent": body.get("intent") if isinstance(body, dict) else None,
                "doctors": summarize_doctors(body.get("doctors", [])) if isinstance(body, dict) else [],
                "ai_response": (body.get("ai_response") if isinstance(body, dict) else None)}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def get_doctor(doctor_id):
    try:
        r = requests.get(f"{BASE}/doctors/{doctor_id}", timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def get_chunks(doctor_id):
    try:
        r = requests.get(f"{BASE}/doctors/{doctor_id}/chunks", timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def by_specialty(specialty):
    try:
        r = requests.get(f"{BASE}/search/doctors/by-specialty", params={"specialty": specialty}, timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def semantic(q, n=5):
    try:
        r = requests.get(f"{BASE}/search/doctors/semantic", params={"q": q, "n": n}, timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def assist(message):
    try:
        r = requests.post(f"{BASE}/appointment/assist", json={"message": message}, timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def quick_book(doctor_id):
    try:
        r = requests.get(f"{BASE}/appointment/quick-book/{doctor_id}", timeout=TIMEOUT)
        return {"status": r.status_code, "body": r.json() if r.content else None}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


results = {}

# A. Symptom -> Specialty
results["PMBK-A1"] = search("I have chest pain, need a heart doctor in Perumbakkam")
results["PMBK-A2"] = search("skin doctor for acne")
results["PMBK-A3"] = search("breathing difficulty, need a lung doctor")
results["PMBK-A4"] = search("kidney specialist")
results["PMBK-A5"] = search("ear pain, need an ENT doctor")

# B. Stem normalization
results["PMBK-B1"] = search("orthopedic doctor")
results["PMBK-B2"] = search("orthopaedic surgeon")
results["PMBK-B3a"] = search("gynecologist")
results["PMBK-B3b"] = search("gynaecologist")
results["PMBK-B4"] = by_specialty("Orthopaedics")

# C. Language filtering
results["PMBK-C1"] = search("Find me an Orthopedic doctor in Chennai who speaks Telugu")
results["PMBK-C2"] = search("Cardiologist who speaks Telugu")
results["PMBK-C3"] = search("Gynaecologist speaking Telugu")
results["PMBK-C4"] = search("orthopaedic doctor who speaks Malayalam")
results["PMBK-C5"] = search("Anaesthesiologist who speaks Telugu")

# D. Name lookup
results["PMBK-D1"] = search("Book appointment with Dr. Ajit Yadav")
results["PMBK-D2"] = search("Tell me about Dr Susan George")
results["PMBK-D3"] = get_doctor("dr-karthik-v-c-chn")
results["PMBK-D4"] = get_doctor("dr-does-not-exist-chn")
results["PMBK-D5"] = search("Dr Ajith Yadev")

# E. Known-gap filters
results["PMBK-E1"] = search("Cardiologist with more than 20 years experience")
results["PMBK-E2"] = search("Cheapest consultation doctor")

# F. Appointment assistant
results["PMBK-F1"] = assist("I want to book an appointment with Dr. Ajit Yadav")
results["PMBK-F2"] = assist("Find a cardiologist")
results["PMBK-F3"] = quick_book("dr-ajit-yadav--chn")
results["PMBK-F4"] = quick_book("dr-nobody-chn")

# G. Tenant isolation
results["PMBK-G1"] = search("cardiologist", tenant_id="glh-chn")
results["PMBK-G2"] = search("cardiologist", tenant_id="glh-adyar")
results["PMBK-G3"] = search("cardiologist")

# H. Negative / robustness
results["PMBK-H1"] = search("asdkjaskjd123")
results["PMBK-H2"] = search("podiatrist")
results["PMBK-H3"] = search("orthopedic dermatologist")
results["PMBK-H4"] = search("'; DROP TABLE doctors; --")
results["PMBK-H5"] = search("")

# I. Direct graph/vector
results["PMBK-I1"] = semantic("heart specialist", n=5)
results["PMBK-I2"] = by_specialty("Nephrology")
results["PMBK-I3"] = get_chunks("dr-ajit-yadav--chn")

with open("regression_results_raw.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

# H4 verification: doctors table must still have 79 rows after the injection attempt
conn = sqlite3.connect("src/workflows/data/db/knowledge_base.db")
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM doctors")
count_after = cur.fetchone()[0]
conn.close()
with open("regression_results_raw.json", "r+", encoding="utf-8") as f:
    data = json.load(f)
    data["_H4_doctor_count_after"] = count_after
    f.seek(0)
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.truncate()

print("DONE. Results written to regression_results_raw.json")
print("doctors count after H4 injection attempt:", count_after)
