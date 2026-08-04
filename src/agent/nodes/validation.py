"""
validation node — Check what info is still missing.
Pure Python. Dynamic phone & search phase validation.
Writes to runtime.needs_info.
"""

import re
import logging
import requests
from datetime import datetime, timedelta
from src.agent.state import AgentState
from src.agent.rules import VALIDATION_RULES
import config

logger = logging.getLogger("agent_nodes")


def _lookup_appointment_by_phone(phone: str, tenant_id: str) -> dict:
    """Lookup the latest active appointment from DB using patient phone number."""
    try:
        resp = requests.get(
            f"{config.WORKFLOWS_API_URL}/appointments/lookup",
            params={"identifier": phone, "client_id": tenant_id},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            appointments = data if isinstance(data, list) else [data]
            # Return the most recent active appointment
            for appt in appointments:
                if appt.get("appointment_id") or appt.get("reference_id"):
                    return {
                        "appointment_id": appt.get("appointment_id") or appt.get("reference_id"),
                        "doctor_name":    appt.get("doctor_name"),
                        "department":     appt.get("department"),
                        "date":           appt.get("date"),
                        "time":           appt.get("time"),
                        "city":           appt.get("city"),
                        "hospital_name":  appt.get("hospital_name"),
                    }
    except Exception as e:
        logger.warning(f"  [NODE 5: VALIDATE] Could not auto-lookup appointment: {e}")
    return {}


def validate(state: AgentState) -> dict:
    """
    Check which required fields are still missing for this workflow + intent.
    Automatically resolves patient_phone from state["user_id"] if missing.
    Dynamically updates relative dates and slot inquiry requests.
    For reschedule/cancel: auto-fetches appointment_id from DB by phone if missing.
    """
    wf_type = state["workflow"]["workflow_type"]
    intent  = state["conversation"]["intent"]
    data    = {**state["workflow"]["data"]}
    user_id = state.get("user_id")
    msg_lower = state["conversation"]["last_user_message"].lower()

    # Auto-populate patient_phone from incoming user_id (WhatsApp phone number)
    if not data.get("patient_phone") and user_id:
        data["patient_phone"] = user_id

    # Auto-resolve relative dates dynamically (today, tomorrow, monday..sunday)
    if not data.get("date") or not re.match(r'^\d{4}-\d{2}-\d{2}$', str(data.get("date"))):
        raw_val = str(data.get("date") or "").lower().strip()
        now = datetime.now()
        target_parsed = None

        if "today" in msg_lower or "today" in raw_val:
            target_parsed = now.strftime("%Y-%m-%d")
        elif "tomorrow" in msg_lower or "tomorrow" in raw_val:
            target_parsed = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            import calendar
            for idx, day in enumerate(calendar.day_name):
                d_lower = day.lower()
                if d_lower in msg_lower or d_lower in raw_val or d_lower[:3] in msg_lower:
                    current_idx = now.weekday()
                    days_ahead = idx - current_idx
                    if days_ahead <= 0:
                        days_ahead += 7
                    target_parsed = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                    break

        if target_parsed:
            data["date"] = target_parsed
            logger.info(f"  [NODE 5: VALIDATE] Auto-resolved date='{target_parsed}' from relative term")

    # For reschedule/cancel/view: if appointment_id missing, look it up from DB by phone
    if intent in ["RESCHEDULE_APPOINTMENT", "CANCEL_APPOINTMENT", "VIEW_APPOINTMENT"] and not data.get("appointment_id"):
        phone = data.get("patient_phone") or user_id
        if phone:
            looked_up = _lookup_appointment_by_phone(phone, state.get("tenant_id", ""))
            if looked_up.get("appointment_id"):
                logger.info(f"  [NODE 5: VALIDATE] Auto-resolved appointment_id={looked_up['appointment_id']} from DB for phone={phone}")
                # Merge — only fill missing fields, don't override what user explicitly said
                for key, val in looked_up.items():
                    if val and not data.get(key):
                        data[key] = val

    # If user is asking for available slots OR rescheduling without specifying a specific new time string in the current message:
    has_new_time_in_msg = any(char.isdigit() for char in msg_lower) and any(w in msg_lower for w in [":", "am", "pm", "o'clock"])
    is_slot_request = any(w in msg_lower for w in ["slot", "slots", "available", "availability", "free"])

    if intent == "RESCHEDULE_APPOINTMENT" and not has_new_time_in_msg:
        data.pop("time", None)
    elif is_slot_request:
        data.pop("time", None)

    has_doctor = bool(data.get("doctor_id") or data.get("doctor_name"))
    has_city   = bool(data.get("city") or data.get("location"))

    # During search phase or when initiating booking, if city is missing, require city to narrow down options
    if intent in ["SEARCH_DOCTOR", "BOOK_APPOINTMENT"] and not has_doctor and not has_city:
        needs = ["city"]
    elif intent == "SEARCH_DOCTOR" or (intent == "BOOK_APPOINTMENT" and not has_doctor):
        needs = []
    else:
        required = VALIDATION_RULES.get((wf_type, intent), [])
        needs = [f for f in required if not (has_doctor if f == "doctor_id" else data.get(f))]

    logger.info(f"  [NODE 5: VALIDATE] Workflow: '{wf_type}' | Intent: '{intent}' | Needs Info: {needs}")
    return {"runtime": {**state["runtime"], "needs_info": needs}, "workflow": {**state["workflow"], "data": data}}
