"""
tool node — Execute tool via registry with single-node bulk search & state caching.
Reads runtime.next_action to route doctor search, bulk availability, or booking/reschedule/cancel calls.
"""

import logging
from datetime import datetime, timedelta
from src.agent.state import AgentState
from src.agent.constants import normalize_text
from src.agent.nodes._shared import registry
from src.tools.models import ToolRequest

logger = logging.getLogger("agent_nodes")


# ── Modular Helpers ─────────────────────────────────────────────────────────

def resolve_doctor(data: dict, search_cache: list, default_client_id: str) -> dict:
    """
    Resolve doctor_id and client_id dynamically from workflow data, search cache, or GraphRAG search.
    """
    doc_id = data.get("doctor_id")
    client_id = data.get("client_id") or default_client_id
    doc_name = data.get("doctor_name") or data.get("doctor")

    # 1. Check existing search cache
    if not doc_id and doc_name and search_cache:
        name_norm = normalize_text(doc_name)
        for search_doc in search_cache:
            cand_name = normalize_text(search_doc.get("doctor_name", ""))
            if name_norm in cand_name or cand_name in name_norm or any(t in cand_name for t in name_norm.split() if len(t) > 3):
                doc_id = search_doc.get("doctor_id") or search_doc.get("sql_id")
                client_id = search_doc.get("client_id") or client_id
                logger.info(f"  [NODE 6: RESOLVED DOCTOR FROM CACHE] '{doc_name}' -> ID: {doc_id} | Client: {client_id}")
                break

    # 2. Dynamic GraphRAG lookup if doc_id is missing or looks like a plain name string
    target_query = doc_id if (doc_id and (" " in str(doc_id) or str(doc_id).startswith("Dr."))) else doc_name
    city_val = data.get("city") or data.get("location")
    if target_query and city_val and city_val.lower() not in str(target_query).lower():
        target_query = f"{target_query} in {city_val}"

    if target_query and (not doc_id or " " in str(doc_id) or str(doc_id).startswith("Dr.")):
        try:
            from src.agent.nodes._shared import registry
            from src.tools.models import ToolRequest
            logger.info(f"  [NODE 6: DYNAMIC GRAPHRAG RESOLVER] Querying GraphRAG for doctor: '{target_query}'")
            s_req = ToolRequest(operation="search", payload={"q": target_query, "n": 5, "tenant_id": default_client_id})
            s_resp = registry.route(s_req)
            if s_resp and s_resp.success and isinstance(s_resp.data, list) and s_resp.data:
                query_tokens = [t.lower() for t in target_query.replace("Dr.", "").split() if len(t) >= 3]
                matched = [d for d in s_resp.data if any(t in d.get("doctor_name", "").lower() for t in query_tokens)]
                
                if len(matched) > 1:
                    logger.info(f"  [NODE 6: MULTIPLE DOCTORS MATCHED] '{target_query}' -> {len(matched)} candidate doctors found.")
                    return {"doctor_id": None, "client_id": client_id, "multiple_doctors": matched}
                elif matched:
                    top_doc = matched[0]
                    doc_id = top_doc.get("doctor_id") or top_doc.get("sql_id") or top_doc.get("id")
                    client_id = top_doc.get("client_id") or client_id
                    logger.info(f"  [NODE 6: GRAPHRAG RESOLVED DOCTOR] '{target_query}' -> Matched '{top_doc.get('doctor_name')}' (ID: {doc_id})")
                else:
                    top_doc = s_resp.data[0]
                    doc_id = top_doc.get("doctor_id") or top_doc.get("sql_id") or top_doc.get("id")
                    client_id = top_doc.get("client_id") or client_id
        except Exception as e:
            logger.warning(f"  [NODE 6: GRAPHRAG RESOLVER FAILED] {e}")

    if not doc_id and doc_name:
        doc_id = doc_name

    return {"doctor_id": doc_id, "client_id": client_id}


def _build_book_payload(state: AgentState, date_val: str, client_id: str) -> dict:
    data = state["workflow"]["data"]
    search_cache = state["runtime"].get("search_results", [])
    doc_info = resolve_doctor(data, search_cache, client_id)

    # Auto-resolve time_val if missing from search cache open slots
    time_val = data.get("time")
    if not time_val and search_cache:
        for search_doc in search_cache:
            if doc_info["doctor_id"] == search_doc.get("doctor_id") and search_doc.get("available_times"):
                time_val = search_doc["available_times"][0]
                logger.info(f"  [NODE 6: AUTO-RESOLVED TIME] Assigned open slot '{time_val}' for doctor {doc_info['doctor_id']}")
                break

    notes = ", ".join(data["symptoms"]) if isinstance(data.get("symptoms"), list) else (data.get("symptoms") or "Appointment Booking")
    payload = {
        "client_id":     doc_info["client_id"],
        "doctor_id":     doc_info["doctor_id"],
        "date":          data.get("date") or date_val,
        "time":          time_val,
        "patient_phone": data.get("patient_phone") or state.get("user_id"),
        "notes":         notes,
    }
    return {k: v for k, v in payload.items() if v is not None}


def _build_reschedule_payload(state: AgentState, date_val: str, client_id: str) -> dict:
    data = state["workflow"]["data"]
    payload = {
        "client_id":      data.get("client_id") or client_id,
        "appointment_id": data.get("appointment_id"),
        "new_date":       data.get("date") or date_val,
        "new_time":       data.get("time"),
    }
    return {k: v for k, v in payload.items() if v is not None}


def _build_cancel_payload(state: AgentState, date_val: str, client_id: str) -> dict:
    data = state["workflow"]["data"]
    payload = {
        "client_id":      data.get("client_id") or client_id,
        "appointment_id": data.get("appointment_id"),
    }
    return {k: v for k, v in payload.items() if v is not None}


PAYLOAD_BUILDERS = {
    "book":       _build_book_payload,
    "reschedule": _build_reschedule_payload,
    "cancel":     _build_cancel_payload,
}


# ── Node Entry Point ─────────────────────────────────────────────────────────

def execute_tool(state: AgentState) -> dict:
    """Build ToolRequest from state, route through registry, merge results, and update tool state."""
    action = state["runtime"].get("next_action") or "search"
    data   = state["workflow"]["data"]
    
    now = datetime.now()
    today_date_str = now.strftime("%Y-%m-%d")
    tomorrow_date_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # If user provided a date explicitly, use it. Otherwise, if past clinical hours (> 17:00 / 5 PM), default to tomorrow!
    if data.get("date"):
        date_val = data.get("date")
    else:
        date_val = tomorrow_date_str if now.hour >= 17 else today_date_str

    client_id = data.get("client_id") or state["tenant_id"]

    # Action 1: Search Doctors + Bulk Availability + Python Merge
    if action in ["search", "SEARCH", "SEARCH_DOCTORS"]:
        logger.info(f"  [NODE 6: EXECUTE_TOOL] Executing Single-Node Search + Bulk Slot Retrieval...")
        
        known_doc_name = data.get("doctor_name")
        known_doc_id   = data.get("doctor_id")

        if known_doc_id or known_doc_name:
            doc_info = resolve_doctor(data, [], client_id)
            if doc_info.get("multiple_doctors"):
                doctors = doc_info["multiple_doctors"]
                search_msg = f"Found {len(doctors)} doctors matching '{known_doc_name}'"
                logger.info(f"  [NODE 6: EXECUTE_TOOL] Found {len(doctors)} multiple doctors matching '{known_doc_name}'. Fetching bulk slots for all candidates...")
            else:
                doc_id   = doc_info.get("doctor_id") or known_doc_id or known_doc_name
                c_id     = doc_info.get("client_id") or client_id
                
                logger.info(f"  [NODE 6: EXECUTE_TOOL] Targeted single doctor search for '{known_doc_name or doc_id}' (Bypassing GraphRAG broad search)")
                doctors = [{
                    "doctor_id":      doc_id,
                    "doctor_name":    known_doc_name or f"Dr. {doc_id}",
                    "department":     data.get("department") or "General Medicine",
                    "branch_name":    data.get("hospital_name") or "Gleneagles Hospitals",
                    "client_id":      c_id,
                }]
                search_msg = f"Targeted slots for {known_doc_name or doc_id}"
        else:
            # Broad GraphRAG Doctor Search via Knowledge Base API
            dept = data.get("department")
            city = data.get("city") or data.get("location")

            if dept and city:
                search_query = f"{dept} doctor in {city}"
            elif dept:
                search_query = f"{dept} doctor"
            else:
                search_query = state["conversation"]["last_user_message"]

            logger.info(f"  [NODE 6: EXECUTE_TOOL] Search Query: '{search_query}'")

            search_req = ToolRequest(operation="search", payload={"q": search_query, "n": 20, "tenant_id": state["tenant_id"]})
            search_resp = registry.route(search_req)
            doctors = search_resp.data if (search_resp and search_resp.success and isinstance(search_resp.data, list)) else []
            search_msg = search_resp.message if search_resp else "Search completed"

        # Step B: Batch availability — tool handles parallelism, retry, and fault isolation internally
        bulk_req   = ToolRequest(operation="availability_batch", payload={"doctors": doctors, "date": date_val})
        bulk_resp  = registry.route(bulk_req)
        bulk_slots = bulk_resp.data if (bulk_resp and bulk_resp.success and isinstance(bulk_resp.data, dict)) else {}

        # Automatic Rollover: If today's remaining slots are empty (e.g. night time query), fetch tomorrow's slots
        has_slots = any(bulk_slots.get(d["doctor_id"]) for d in doctors)
        if not has_slots and date_val == today_date_str:
            date_val   = tomorrow_date_str
            bulk_req   = ToolRequest(operation="availability_batch", payload={"doctors": doctors, "date": date_val})
            bulk_resp  = registry.route(bulk_req)
            bulk_slots = bulk_resp.data if (bulk_resp and bulk_resp.success and isinstance(bulk_resp.data, dict)) else {}

        # Step C: Pure Python Merging + Dynamic Real-Time Time Filter
        merged_doctors = []
        now_time_str = datetime.now().strftime("%H:%M")

        for d in doctors:
            doc_id = d["doctor_id"]
            slots = bulk_slots.get(doc_id, [])
            
            # Dynamic Real-Time Filter: If date is today, filter out past time slots
            if date_val == today_date_str:
                slots = [s for s in slots if (s.get("time") if isinstance(s, dict) else str(s)) > now_time_str]

            merged_doctors.append({
                **d,
                "slot_date": date_val,
                "slots": slots,
                "available_times": [s.get("time") if isinstance(s, dict) else str(s) for s in slots]
            })

        logger.info(f"  [NODE 6: EXECUTE_TOOL OK] Merged {len(merged_doctors)} doctor(s) with live slot availability.")

        return {
            "tool": {
                "tool_output":  {"data": merged_doctors, "message": search_msg, "error": None},
                "tool_success": True,
                "last_tool":     "search",
                "doctor_results": merged_doctors,
                "availability":   bulk_slots,
            },
            "runtime": {
                **state["runtime"],
                "search_results": merged_doctors,
                "cached_at":      datetime.now().isoformat(),
            }
        }

    # Action 2: Transactional Actions (Book / Reschedule / Cancel)
    op_name = action.lower()
    if op_name in ["book_appointment"]:
        op_name = "book"

    builder = PAYLOAD_BUILDERS.get(op_name)
    if not builder:
        logger.error(f"  [NODE 6: EXECUTE_TOOL ERROR] Unsupported operation '{op_name}'")
        return {
            "tool": {
                "tool_output":  {"error": f"Unsupported operation '{op_name}'"},
                "tool_success": False,
                "last_tool":     op_name,
                "doctor_results": state["tool"].get("doctor_results", []),
                "availability":   state["tool"].get("availability", {}),
            }
        }

    payload = builder(state, date_val, client_id)

    logger.info(
        f"  [NODE 6: EXECUTE_TRANSACTION]\n"
        f"    ↳ Operation : '{op_name}'\n"
        f"    ↳ Payload   : {payload}"
    )

    resp = registry.route(ToolRequest(operation=op_name, payload=payload))
    logger.info(f"  [NODE 6: TOOL_RESULT] Op: '{op_name}' | Success: {resp.success} | Msg: '{resp.message}'")

    updated_workflow_data = {**state["workflow"]["data"]}
    if resp.success and resp.data and isinstance(resp.data, dict) and resp.data.get("appointment_id"):
        updated_workflow_data["appointment_id"] = resp.data["appointment_id"]

    clean_error = resp.error
    if clean_error and "{" in str(clean_error) and "error" in str(clean_error):
        import json
        try:
            err_str = str(clean_error)
            json_str = err_str[err_str.index("{"):err_str.rindex("}") + 1]
            err_obj = json.loads(json_str)
            if isinstance(err_obj, dict) and err_obj.get("error"):
                clean_error = err_obj["error"]
        except Exception:
            pass

    rem_slots = []
    if op_name == "book" and not resp.success:
        try:
            doc_identifier = payload.get("doctor_id") or payload.get("doctor")
            slot_date = payload.get("date") or date_val
            if doc_identifier and slot_date:
                avail_req = ToolRequest(operation="availability", payload={"doctor_id": doc_identifier, "date": slot_date, "client_id": client_id})
                avail_resp = registry.route(avail_req)
                if avail_resp and avail_resp.success and isinstance(avail_resp.data, list):
                    rem_slots = [s.get("time") if isinstance(s, dict) else str(s) for s in avail_resp.data]
                    logger.info(f"  [NODE 6: BOOKING FAILED -> FETCHED REMAINING SLOTS] Found {len(rem_slots)} available slot(s) for '{doc_identifier}' on {slot_date}")
        except Exception as e:
            logger.warning(f"  [NODE 6: FETCH REMAINING SLOTS FAILED] {e}")

    return {
        "workflow": {**state["workflow"], "data": updated_workflow_data},
        "tool": {
            "tool_output":   {
                "data": resp.data or {},
                "message": resp.message,
                "error": clean_error,
                "available_slots": rem_slots,
                "date": payload.get("date") or date_val,
            },
            "tool_success":  resp.success,
            "last_tool":      op_name,
            "doctor_results": state["tool"].get("doctor_results", []),
            "availability":   state["tool"].get("availability", {}),
        }
    }
