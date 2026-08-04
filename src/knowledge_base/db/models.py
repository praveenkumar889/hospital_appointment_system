"""
SQLAlchemy 2.0 ORM models — denormalized, flat schema.

Tables (4):
  hospitals       — 7 Gleneagles locations
  doctors         — 464 doctors, includes denormalized arrays + schedule summary
  schedule_days   — per-date availability (FK → doctors.id)
  time_slots      — individual bookable slots (FK → schedule_days.id)

Storage split:
  SQL  — all referential/transactional facts, denormalized CSV arrays, slot detail
  Neo4j — semantic graph only: PRACTICES_AT, SPECIALIZES_IN, SPEAKS
  ChromaDB — free-text search chunks
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Hospitals ──────────────────────────────────────────────────────────────────

class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String, primary_key=True)      # e.g. "glh-chn"
    name: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[Optional[str]] = mapped_column(String)
    brand_description: Mapped[Optional[str]] = mapped_column(String)
    city: Mapped[Optional[str]] = mapped_column(String)
    state: Mapped[Optional[str]] = mapped_column(String)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    loc_short: Mapped[Optional[str]] = mapped_column(String)
    address: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String)
    emergency_phone: Mapped[Optional[str]] = mapped_column(String)
    booking_base_url: Mapped[Optional[str]] = mapped_column(String)
    url_slug: Mapped[Optional[str]] = mapped_column(String)
    tenant_id: Mapped[str] = mapped_column(String, default="gleneagles", index=True)

    doctors: Mapped[List["Doctor"]] = relationship(
        "Doctor", back_populates="hospital",
        foreign_keys="Doctor.location_id",
        primaryjoin="Hospital.location_id == Doctor.location_id",
        viewonly=True,
    )


# ── Doctor (denormalized + schedule summary) ───────────────────────────────────

class Doctor(Base):
    """
    One row per doctor.
    Arrays (specializations, qualifications, languages) stored as comma-separated text.
    Schedule summary columns (next_available, total_available_slots, etc.) merged here
    — avoids a separate 1:1 doctor_schedules table.
    Full slot detail lives in schedule_days → time_slots.
    """
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(String, primary_key=True)       # slug

    # Identity
    name: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String)
    last_name: Mapped[Optional[str]] = mapped_column(String)
    gender: Mapped[Optional[str]] = mapped_column(String)

    # API identifiers
    numeric_doctor_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)    # → hospitals.location_id
    appointment_type: Mapped[Optional[str]] = mapped_column(String)             # SELF_BOOK / CALL_TO_BOOK

    # Profile
    designation: Mapped[Optional[str]] = mapped_column(String)
    speciality: Mapped[Optional[str]] = mapped_column(String)                  # primary API speciality
    experience_years: Mapped[Optional[int]] = mapped_column(Integer)
    consultation_fee: Mapped[Optional[str]] = mapped_column(String)
    bio: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String)
    profile_url: Mapped[Optional[str]] = mapped_column(Text)
    profile_image_url: Mapped[Optional[str]] = mapped_column(Text)
    booking_url: Mapped[Optional[str]] = mapped_column(Text)

    # Denormalized arrays (comma-separated text)
    specializations: Mapped[Optional[str]] = mapped_column(Text)    # "Cardiology,Cardiac Surgery"
    qualifications: Mapped[Optional[str]] = mapped_column(Text)     # "MBBS,MD,DM"
    languages: Mapped[Optional[str]] = mapped_column(Text)          # "Tamil,English,Telugu"

    # Schedule summary (merged from former doctor_schedules table)
    consultation_types: Mapped[Optional[str]] = mapped_column(String)          # CSV: "VIDEO,IN_PERSON"
    working_days: Mapped[Optional[str]] = mapped_column(String)                # CSV: "Mon,Tue,Wed"
    next_available: Mapped[Optional[str]] = mapped_column(String, index=True)  # "2025-07-01"
    total_available_slots: Mapped[int] = mapped_column(Integer, default=0, index=True)
    scraped_at: Mapped[Optional[str]] = mapped_column(String)
    tenant_id: Mapped[str] = mapped_column(String, default="gleneagles", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    hospital: Mapped[Optional["Hospital"]] = relationship(
        "Hospital", back_populates="doctors",
        foreign_keys=[location_id],
        primaryjoin="Doctor.location_id == Hospital.location_id",
        viewonly=True,
    )
    schedule_days: Mapped[List["ScheduleDay"]] = relationship(
        "ScheduleDay", back_populates="doctor", cascade="all, delete-orphan"
    )


# ── Schedule detail (SQL is authoritative) ─────────────────────────────────────

class ScheduleDay(Base):
    """Per-date availability — one row per doctor per calendar date."""
    __tablename__ = "schedule_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[str] = mapped_column(
        String, ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[str] = mapped_column(String, index=True)
    day_name: Mapped[Optional[str]] = mapped_column(String)
    total_slots: Mapped[int] = mapped_column(Integer, default=0)
    available_slots: Mapped[int] = mapped_column(Integer, default=0)

    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="schedule_days")
    slots: Mapped[List["TimeSlot"]] = relationship(
        "TimeSlot", back_populates="day", cascade="all, delete-orphan"
    )


class TimeSlot(Base):
    """Individual bookable time slot."""
    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_day_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schedule_days.id", ondelete="CASCADE"), index=True
    )
    doctor_id: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)
    time: Mapped[str] = mapped_column(String)
    period: Mapped[Optional[str]] = mapped_column(String)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    slot_type: Mapped[Optional[str]] = mapped_column(String)

    day: Mapped["ScheduleDay"] = relationship("ScheduleDay", back_populates="slots")
