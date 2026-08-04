"""
constants.py — Workflow State & System Constants

All shared state constants live here for clean separation from business validation rules.
"""

from typing import Optional

CLEAR_ON_DEPARTMENT_CHANGE: set[str] = {
    "doctor_id",
    "doctor_name",
    "date",
    "time",
    "slot_id",
    "appointment_id",
    "selected_slot",
    "client_id",
}

# Alias for backward compatibility
DOCTOR_SELECTION_FIELDS = CLEAR_ON_DEPARTMENT_CHANGE


def normalize_text(val: Optional[str]) -> str:
    """Normalize string for safe, case-insensitive comparison."""
    return (val or "").strip().casefold()


