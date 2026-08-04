"""
Database query helpers for Appointment Booking Service.
Extracted for modularity and maintainability.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def lookup_client_name(db: Session, client_id: str) -> str:
    """Find hospital name by client_id."""
    row = db.execute(
        text("SELECT name FROM hospitals WHERE id = :id"),
        {"id": client_id}
    ).fetchone()
    return row[0] if row else (client_id or "Unknown")


def find_doctor(db: Session, client_id: str, doctor_id_or_name: str):
    """Find doctor record by ID or fuzzy name match."""
    clean_search = doctor_id_or_name.replace("Dr.", "").replace("dr.", "").strip()

    # 1. Exact ID
    doc = db.execute(
        text("SELECT id, name, speciality, experience_years FROM doctors WHERE id = :id"),
        {"id": doctor_id_or_name}
    ).fetchone()
    if doc:
        return doc

    # 2. Branch specific doctor match
    branch_suffix = client_id.replace("glh-", "") if client_id and client_id.startswith("glh-") else ""
    if branch_suffix:
        doc = db.execute(
            text("SELECT id, name, speciality, experience_years FROM doctors WHERE (name LIKE :pattern OR id LIKE :pattern) AND id LIKE :suffix"),
            {"pattern": f"%{clean_search}%", "suffix": f"%{branch_suffix}%"}
        ).fetchone()
        if doc:
            return doc

    # 3. Fallback name/ID match
    doc = db.execute(
        text("SELECT id, name, speciality, experience_years FROM doctors WHERE name LIKE :pattern OR id LIKE :pattern"),
        {"pattern": f"%{clean_search}%"}
    ).fetchone()
    if doc:
        return doc

    # 4. Token-based fuzzy matching (e.g. "arjit yadav" -> token "yadav" matches "Ajit Yadav")
    import re
    tokens = [t for t in re.split(r'[-_\s]+', clean_search) if len(t) >= 4 and t.lower() not in ["chn", "lbn", "omb", "per", "dr", "doctor"]]
    for token in tokens:
        doc = db.execute(
            text("SELECT id, name, speciality, experience_years FROM doctors WHERE name LIKE :pattern OR id LIKE :pattern"),
            {"pattern": f"%{token}%"}
        ).fetchone()
        if doc:
            return doc

    return None


import re

def find_slot(db: Session, doc_id: str, date: str, time: str, available_only: bool = True):
    """Find slot ID matching doctor, date, and time criteria."""
    clean_time = re.sub(r'[^\d:]', '', time).strip() if time else ""
    avail_clause = "AND available = 1" if available_only else ""

    # 1. Exact doctor + date + time
    slot = db.execute(
        text(f"SELECT id, available FROM time_slots WHERE doctor_id = :did AND date = :date AND (time = :time OR time = :ctime OR time LIKE :tpat) {avail_clause} ORDER BY available DESC"),
        {"did": doc_id, "date": date, "time": time, "ctime": clean_time, "tpat": f"%{clean_time}%"}
    ).fetchone()
    if slot:
        return slot

    # 2. Check if slot exists regardless of availability (to report booked state)
    if available_only:
        return find_slot(db, doc_id, date, time, available_only=False)

    return None
