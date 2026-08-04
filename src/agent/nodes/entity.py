"""
entity node — Extract entities from conversation and inject memory preferences.
Dynamically extracts phone numbers, symptoms, location, and department inference.
"""

import re
import logging
from datetime import datetime
from langchain_core.messages import HumanMessage
from src.agent.state import AgentState
from src.agent.nodes._shared import llm, prompts

from src.agent.constants import CLEAR_ON_DEPARTMENT_CHANGE, normalize_text

logger = logging.getLogger("agent_nodes")


def extract_entities(state: AgentState) -> dict:
    """LLM extracts booking/workflow fields & dynamic phone numbers from recent messages."""
    recent = "\n".join(f"{m.type}: {m.content}" for m in state["messages"][-6:])
    current_date_str = datetime.now().strftime("%A, %B %d, %Y (%Y-%m-%d)")
    
    prompt = prompts.get("entity", messages=recent, current_date=current_date_str)
    extracted = llm.json_output([HumanMessage(content=prompt)])

    # Normalize extracted date year to 2026 if LLM extracted past year (e.g. 2024 -> 2026)
    raw_date = extracted.get("date")
    if raw_date and isinstance(raw_date, str) and len(raw_date) == 10:
        parts = raw_date.split("-")
        if len(parts) == 3:
            try:
                if int(parts[0]) < 2026:
                    extracted["date"] = f"2026-{parts[1]}-{parts[2]}"
                    logger.info(f"  [NODE 3: DATE YEAR NORMALIZED] '{raw_date}' -> '{extracted['date']}'")
            except ValueError:
                pass

    current_data = state["workflow"]["data"]
    merged = {**current_data}

    # Normalize department strings using shared helper
    new_dept_raw = extracted.get("department")
    old_dept_raw = current_data.get("department")
    
    new_dept_norm = normalize_text(new_dept_raw)
    old_dept_norm = normalize_text(old_dept_raw)

    # Clear stale doctor selection ONLY if user explicitly switches to a DIFFERENT department
    if new_dept_norm:
        if old_dept_norm and new_dept_norm != old_dept_norm:
            if not extracted.get("doctor_name") and not extracted.get("doctor_id"):
                for field in CLEAR_ON_DEPARTMENT_CHANGE:
                    merged.pop(field, None)
                logger.info(f"  [NODE 3: DEPARTMENT CHANGED] '{old_dept_raw}' -> '{new_dept_raw}' | Cleared stale doctor state.")
        merged["department"] = new_dept_raw


    # Merge non-null extracted fields
    for k, v in extracted.items():
        if v is not None:
            merged[k] = v

    # Dynamic Phone & Appointment ID Extraction: Regex check from last user message
    last_msg = state["conversation"]["last_user_message"]
    phone_matches = re.findall(r'\b\d{10,12}\b', last_msg)
    if phone_matches and not merged.get("patient_phone"):
        merged["patient_phone"] = phone_matches[0]
        logger.info(f"  [NODE 3: DYNAMIC PHONE EXTRACTED] Found phone '{phone_matches[0]}' in user message")

    apt_matches = re.findall(r'\bAPT-[A-Za-z0-9]+\b', last_msg, re.IGNORECASE)
    if apt_matches:
        merged["appointment_id"] = apt_matches[0].upper()
        logger.info(f"  [NODE 3: DYNAMIC APPT ID EXTRACTED] Found Appointment ID '{apt_matches[0].upper()}' in user message")

    # Dynamic Phone Fallback: Default to incoming WhatsApp sender phone (user_id)
    if not merged.get("patient_phone") and state.get("user_id"):
        merged["patient_phone"] = state["user_id"]

    logger.info(f"  [NODE 3: EXTRACT_ENTITIES] Extracted: {extracted} | Merged Data: {merged}")
    return {"workflow": {**state["workflow"], "data": merged}}


def inject_memory(state: AgentState) -> dict:
    """Fill missing workflow fields dynamically from user's saved preferences. No LLM."""
    data  = {**state["workflow"]["data"]}
    prefs = state["memory"].get("preferences", {})

    injected_keys = []
    # Dynamically inject preference values into missing workflow data fields
    for key, value in prefs.items():
        target_field = key.replace("preferred_", "")
        if target_field == "branch":
            target_field = "client_id"
        if target_field in ["doctor_name", "doctor_id", "doctor"]:
            continue
        if not data.get(target_field) and value:
            data[target_field] = value
            injected_keys.append(f"{target_field}={value}")

    # Ensure patient_phone is always dynamically populated from user_id if not present
    if not data.get("patient_phone") and state.get("user_id"):
        data["patient_phone"] = state["user_id"]
        injected_keys.append(f"patient_phone={state['user_id']}")

    logger.info(f"  [NODE 4: INJECT_MEMORY] Injected stored preferences: {injected_keys} | Final Data: {data}")
    return {"workflow": {**state["workflow"], "data": data}}
