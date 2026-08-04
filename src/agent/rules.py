"""
rules.py — Dynamic Validation & Decision Rules

All workflow rules live here. No node changes needed to add new workflows.
"""


# ── Validation Rules ───────────────────────────────────────────────────────
# Key = (workflow_type, intent)
# Value = list of required fields in workflow.data
VALIDATION_RULES: dict[tuple[str, str], list[str]] = {
    ("booking", "BOOK_APPOINTMENT"):       ["city", "doctor_id", "date", "time", "patient_phone"],
    ("booking", "SEARCH_DOCTOR"):          ["city"],
    ("booking", "CANCEL_APPOINTMENT"):     ["appointment_id"],
    ("booking", "RESCHEDULE_APPOINTMENT"): ["appointment_id", "date", "time"],
    ("booking", "VIEW_APPOINTMENT"):       [],
    ("booking", "MANAGE_APPOINTMENT"):     [],
}


# ── Decision Rules ─────────────────────────────────────────────────────────
# Maps (intent, condition) → tool operation
# Decision node uses these to determine next_action
DECISION_MAP: dict[str, dict] = {
    "SEARCH_DOCTOR": {
        "default": "search",
    },
    "BOOK_APPOINTMENT": {
        "no_doctor":  "search",       # don't have a doctor yet → search first
        "ready":      "book",         # have all fields → book
    },
    "CANCEL_APPOINTMENT": {
        "default":    "cancel",
    },
    "RESCHEDULE_APPOINTMENT": {
        "default":    "reschedule",
    },
    "VIEW_APPOINTMENT": {
        "default":    "ask_user",     # view appointment → display details cleanly (never cancel!)
    },
    "MANAGE_APPOINTMENT": {
        "default":    "ask_user",     # generic manage → ask user / show details
    },
}


# ── Intent → Operation (simple direct mapping for tool node) ───────────────
INTENT_TO_OPERATION: dict[str, str] = {
    "SEARCH_DOCTOR":          "search",
    "BOOK_APPOINTMENT":       "book",
    "CANCEL_APPOINTMENT":     "cancel",
    "RESCHEDULE_APPOINTMENT": "reschedule",
    "VIEW_APPOINTMENT":       "ask_user",
}
