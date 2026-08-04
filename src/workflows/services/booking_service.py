from datetime import datetime
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.workflows.config import get_client_config, get_database_url
from src.workflows.services.booking_helpers import (
    find_doctor,
    find_slot,
    lookup_client_name,
)


class AppointmentBookingService:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.config = get_client_config(client_id)
        engine = create_engine(get_database_url(client_id), connect_args={"check_same_thread": False})
        self.db = sessionmaker(bind=engine)()

    def _lookup_client_name(self) -> str:
        return lookup_client_name(self.db, self.client_id)

    def _find_doctor(self, doctor_id_or_name: str):
        return find_doctor(self.db, self.client_id, doctor_id_or_name)

    def _find_slot(self, doc_id: str, date: str, time: str):
        return find_slot(self.db, doc_id, date, time)

    def get_availability(self, doctor_id: str, date: str) -> list:
        try:
            doctor = self._find_doctor(doctor_id)
            actual_did = doctor[0] if doctor else doctor_id
            
            slots = self.db.execute(
                text("SELECT id, time, period FROM time_slots WHERE doctor_id = :did AND date = :date AND available = 1 ORDER BY time"),
                {"did": actual_did, "date": date}
            ).fetchall()
            raw_slots = [{"slot_id": s[0], "time": s[1], "period": s[2]} for s in slots]
            
            # Dynamic Real-Time Time Filter: If date is today, only show future time slots
            today_str = datetime.now().strftime("%Y-%m-%d")
            if date == today_str:
                now_time_str = datetime.now().strftime("%H:%M")
                raw_slots = [s for s in raw_slots if s["time"] > now_time_str]
                
            return raw_slots
        finally:
            self.db.close()

    def book(self, phone: str, doctor_id: str, date: str, time: str, notes: str = None) -> dict:
        try:
            doctor = self._find_doctor(doctor_id)
            if not doctor:
                raise ValueError(f"Doctor '{doctor_id}' not found in database")

            actual_doctor_id, doctor_name, speciality, experience_years = doctor[0], doctor[1], doctor[2] or "General", doctor[3]

            import re
            clean_time = re.sub(r'[^\d:]', '', time).strip() if time else ""

            # 1. Double Booking Prevention: Check if active appointment already exists for same doctor, date, time
            existing_appt = self.db.execute(
                text("SELECT id FROM appointments WHERE doctor_id = :did AND date = :date AND (time = :time OR time LIKE :tpat) AND status IN ('booked', 'confirmed')"),
                {"did": actual_doctor_id, "date": date, "time": time, "tpat": f"%{clean_time}%"}
            ).fetchone()
            if existing_appt:
                raise ValueError(f"The slot at {time} on {date} for Dr. {doctor_name} is already booked. Please select another time slot.")

            # 2. Check time_slots availability
            slot = self._find_slot(actual_doctor_id, date, time)
            slot_id = slot[0] if slot else None
            is_available = slot[1] if (slot and len(slot) > 1) else 1

            if is_available == 0:
                raise ValueError(f"The slot at {time} on {date} for Dr. {doctor_name} is no longer available. Please select another time slot.")

            if slot_id:
                self.db.execute(text("UPDATE time_slots SET available = 0 WHERE id = :id"), {"id": slot_id})

            appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"
            self.db.execute(
                text("INSERT INTO appointments (id, client_id, patient_phone, doctor_id, date, time, slot_id, status, notes, created_at) VALUES (:id, :cid, :phone, :doc, :date, :time, :slot, :status, :notes, :created)"),
                {
                    "id": appointment_id, "cid": self.client_id, "phone": phone, "doc": actual_doctor_id,
                    "date": date, "time": time, "slot": slot_id, "status": "booked", "notes": notes, "created": datetime.utcnow().isoformat()
                }
            )
            self.db.commit()

            return {
                "appointment_id": appointment_id, "status": "booked", "doctor_name": doctor_name,
                "doctor_id": actual_doctor_id, "speciality": speciality, "experience_years": experience_years,
                "date": date, "time": time, "patient_phone": phone, "client_id": self.client_id,
                "client_name": self._lookup_client_name(), "notes": notes, "booked_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.close()

    def reschedule(self, appointment_id: str, new_date: str, new_time: str) -> dict:
        try:
            existing = self.db.execute(
                text("SELECT slot_id, doctor_id, id, date, time FROM appointments WHERE id = :id OR notes LIKE :pat ORDER BY created_at DESC LIMIT 1"),
                {"id": appointment_id, "pat": f"%{appointment_id}%"}
            ).fetchone()
            if not existing:
                existing = self.db.execute(
                    text("SELECT slot_id, doctor_id, id, date, time FROM appointments WHERE status = 'booked' OR status = 'confirmed' ORDER BY created_at DESC LIMIT 1")
                ).fetchone()

            if not existing:
                raise ValueError(f"Appointment '{appointment_id}' not found")

            old_slot_id, doctor_id, db_app_id, old_date, old_time = existing[0], existing[1], existing[2], existing[3], existing[4]

            # 1. Release old time slot
            if old_slot_id:
                self.db.execute(text("UPDATE time_slots SET available = 1 WHERE id = :id"), {"id": old_slot_id})

            # 2. Reserve new time slot using find_slot helper
            new_slot = find_slot(self.db, doctor_id, new_date, new_time)
            new_slot_id = new_slot[0] if new_slot else None

            if new_slot_id:
                self.db.execute(text("UPDATE time_slots SET available = 0 WHERE id = :id"), {"id": new_slot_id})

            # 3. Update appointment record
            self.db.execute(
                text("UPDATE appointments SET slot_id = :new_slot, date = :date, time = :time WHERE id = :id"),
                {"new_slot": new_slot_id, "date": new_date, "time": new_time, "id": db_app_id}
            )
            self.db.commit()

            return {
                "appointment_id": db_app_id, "status": "rescheduled", "new_date": new_date, "new_time": new_time,
                "client_id": self.client_id, "message": f"Appointment '{db_app_id}' has been successfully rescheduled to {new_date} at {new_time}.",
                "rescheduled_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.close()

    def cancel(self, appointment_id: str) -> dict:
        try:
            appointment = self.db.execute(
                text("SELECT slot_id, status FROM appointments WHERE id = :id AND client_id = :cid"),
                {"id": appointment_id, "cid": self.client_id}
            ).fetchone()
            if not appointment:
                raise ValueError("Appointment not found")

            slot_id, status = appointment[0], appointment[1]

            if status == "cancelled":
                raise ValueError("Appointment already cancelled")

            self.db.execute(text("UPDATE time_slots SET available = 1 WHERE id = :id"), {"id": slot_id})
            self.db.execute(
                text("UPDATE appointments SET status = 'cancelled', cancelled_at = :cancelled WHERE id = :id"),
                {"cancelled": datetime.utcnow().isoformat(), "id": appointment_id}
            )
            self.db.commit()

            return {
                "appointment_id": appointment_id, "status": "cancelled",
                "client_id": self.client_id, "cancelled_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.close()

    def get_appointment(self, identifier: str) -> dict:
        """Lookup active appointment by appointment_id or patient_phone."""
        try:
            row = self.db.execute(
                text("""
                    SELECT a.id, a.doctor_id, d.name, a.date, a.time, a.status, a.patient_phone,
                           h.name, h.city, d.speciality
                    FROM appointments a
                    LEFT JOIN doctors d ON a.doctor_id = d.id
                    LEFT JOIN hospitals h ON d.location_id = h.location_id
                    WHERE (a.id = :id OR a.patient_phone = :id OR a.patient_phone LIKE :phone)
                      AND a.status != 'cancelled'
                    ORDER BY a.created_at DESC LIMIT 1
                """),
                {"id": identifier, "phone": f"%{identifier}%"}
            ).fetchone()

            if not row:
                return {"found": False, "message": "No active appointment found"}

            return {
                "found":          True,
                "appointment_id": row[0],
                "doctor_id":      row[1],
                "doctor_name":    row[2] or row[1],
                "date":           row[3],
                "time":           row[4],
                "status":         row[5],
                "patient_phone":  row[6],
                "hospital_name":  row[7] or "Gleneagles Hospitals",
                "city":           row[8] or "",
                "department":     row[9] or "",
            }
        finally:
            self.db.close()