"""
src/db/loader.py

Load merged canonical data into SQLite (flat denormalized schema).

Load order (respects FK constraints):
  1. hospitals
  2. doctors   (location_id → hospitals.location_id; arrays as CSV; schedule summary nulled)
  3. schedules  → updates doctor schedule-summary columns + loads schedule_days + time_slots
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.knowledge_base.db.models import Doctor, Hospital, ScheduleDay, TimeSlot


def _csv(items: list) -> str | None:
    cleaned = [str(i).strip() for i in items if i and str(i).strip()]
    return ",".join(cleaned) if cleaned else None


def _upsert(session: Session, model, conflict_col: str, row: dict) -> None:
    stmt = (
        sqlite_insert(model)
        .values(**row)
        .on_conflict_do_update(index_elements=[conflict_col], set_=row)
    )
    session.execute(stmt)


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_hospitals(session: Session, hospitals: list[dict]) -> None:
    for h in hospitals:
        _upsert(session, Hospital, "id", {
            "id":              h["id"],
            "name":            h.get("name", ""),
            "branch":          h.get("branch"),
            "brand_description": h.get("brand_description"),
            "city":            h.get("city"),
            "state":           h.get("state"),
            "location_id":     h.get("location_id"),
            "loc_short":       h.get("loc_short"),
            "address":         h.get("address"),
            "phone":           h.get("phone"),
            "emergency_phone": h.get("emergency_phone"),
            "booking_base_url": h.get("booking_base_url"),
            "url_slug":        h.get("url_slug"),
            "tenant_id":       h.get("tenant_id", "gleneagles"),
        })
    session.commit()
    logger.info(f"SQL: {len(hospitals)} hospitals loaded")


def load_doctors(session: Session, doctors: list[dict]) -> None:
    for doc in doctors:
        quals = []
        for q in (doc.get("qualifications") or []):
            quals.append(q["degree"] if isinstance(q, dict) else q)

        _upsert(session, Doctor, "id", {
            "id":                    doc["id"],
            "name":                  doc.get("name", ""),
            "first_name":            doc.get("first_name"),
            "last_name":             doc.get("last_name"),
            "gender":                doc.get("gender"),
            "numeric_doctor_id":     doc.get("numeric_doctor_id"),
            "department_id":         doc.get("department_id"),
            "location_id":           doc.get("location_id"),
            "appointment_type":      doc.get("appointment_type"),
            "designation":           doc.get("designation"),
            "speciality":            doc.get("speciality"),
            "experience_years":      doc.get("experience_years"),
            "consultation_fee":      doc.get("consultation_fee"),
            "bio":                   doc.get("bio"),
            "phone":                 doc.get("phone"),
            "profile_url":           doc.get("profile_url"),
            "profile_image_url":     doc.get("profile_image_url"),
            "booking_url":           doc.get("booking_url"),
            "specializations":       _csv(doc.get("specializations") or []),
            "qualifications":        _csv(quals),
            "languages":             _csv(doc.get("languages") or []),
            "tenant_id":             doc.get("tenant_id", "gleneagles"),
            # Schedule summary defaults — populated by load_schedules()
            "consultation_types":    None,
            "working_days":          None,
            "next_available":        None,
            "total_available_slots": 0,
            "scraped_at":            None,
        })
    session.commit()
    logger.info(f"SQL: {len(doctors)} doctors loaded")


def load_schedules(session: Session, schedules: list[dict]) -> None:
    for sched in schedules:
        did = sched.get("doctor_id", "")
        if not did:
            continue

        days_data = sched.get("schedule_days", [])
        total_avail = sum(d.get("available_slots", 0) for d in days_data)
        working_days = sorted({
            d["day_name"] for d in days_data
            if d.get("total_slots", 0) > 0 and d.get("day_name")
        })
        next_avail = next(
            (d["date"] for d in days_data if d.get("available_slots", 0) > 0),
            None,
        )
        booking_url = sched.get("booking_url")
        ctypes = ",".join(sched.get("consultation_types") or [])

        # Update schedule-summary columns on the doctor row
        session.execute(
            sqlite_insert(Doctor).values(
                id=did,
                name="",                          # placeholder; ON CONFLICT only updates listed cols
                consultation_types=ctypes or None,
                working_days=",".join(working_days) or None,
                next_available=sched.get("next_available") or next_avail,
                total_available_slots=total_avail,
                scraped_at=sched.get("scraped_at"),
                **({"booking_url": booking_url} if booking_url else {}),
            ).on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "consultation_types":    ctypes or None,
                    "working_days":          ",".join(working_days) or None,
                    "next_available":        sched.get("next_available") or next_avail,
                    "total_available_slots": total_avail,
                    "scraped_at":            sched.get("scraped_at"),
                    **({"booking_url": booking_url} if booking_url else {}),
                },
            )
        )

        # Clear and reload schedule_days for this doctor
        session.query(ScheduleDay).filter(ScheduleDay.doctor_id == did).delete()

        for day in days_data:
            day_obj = ScheduleDay(
                doctor_id=did,
                date=day.get("date", ""),
                day_name=day.get("day_name"),
                total_slots=day.get("total_slots", 0),
                available_slots=day.get("available_slots", 0),
            )
            session.add(day_obj)
            session.flush()

            for slot in day.get("slots", []):
                session.add(TimeSlot(
                    schedule_day_id=day_obj.id,
                    doctor_id=did,
                    date=day.get("date", ""),
                    time=slot.get("time", ""),
                    period=slot.get("period"),
                    available=slot.get("available", True),
                    slot_type=slot.get("slot_type"),
                ))

    session.commit()
    logger.info(f"SQL: {len(schedules)} schedules loaded")
