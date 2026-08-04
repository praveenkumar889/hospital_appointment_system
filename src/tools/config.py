"""
config.py — Tool Layer Configuration

All URLs loaded from environment. Zero hardcoding.
Endpoints grouped by tool — easy to add new operations without touching tool files.

Required .env keys:
    KB_API_BASE_URL          e.g. http://localhost:8000
    WORKFLOWS_API_BASE_URL   e.g. http://localhost:8001
    TOOL_REQUEST_TIMEOUT     e.g. 10  (seconds, optional)
"""

import os


def _env(key: str, default: str) -> str:
    """Read from environment with a fallback default."""
    return os.getenv(key, default)


# ── Knowledge Base API ─────────────────────────────────────────────────────
_KB_BASE = _env("KB_API_BASE_URL", "http://localhost:8000")

DOCTOR_ENDPOINTS = {
    "search": f"{_KB_BASE}/search/doctors",
    # Add more doctor-related endpoints here as the API grows
    # "by_specialization": f"{_KB_BASE}/search/doctors/by-specialization",
}

# ── Workflows API ──────────────────────────────────────────────────────────
_WF_BASE = _env("WORKFLOWS_API_BASE_URL", "http://localhost:8001")

APPOINTMENT_ENDPOINTS = {
    "availability": f"{_WF_BASE}/appointments/availability",
    "book":         f"{_WF_BASE}/appointments/book",
    "reschedule":   f"{_WF_BASE}/appointments/reschedule",
    "cancel":       f"{_WF_BASE}/appointments/cancel",
}

# ── HTTP ───────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = int(_env("TOOL_REQUEST_TIMEOUT", "30"))
