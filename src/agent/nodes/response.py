"""
response node — Generate the final reply using LLM.
Passes full state (workflow_data, search_results, memory, needs_info) to response prompt.
Includes clean deterministic formatting for successful reschedule and cancel transactions on the current turn.
"""

import re
import logging
from langchain_core.messages import HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.nodes._shared import llm, prompts


logger = logging.getLogger("agent_nodes")


def generate_response(state: AgentState) -> dict:
    """Generate human-readable reply from current state using LLM."""
    intent = state["conversation"]["intent"]
    runtime_state = state.get("runtime", {})
    next_action = runtime_state.get("next_action")
    tool_state = state.get("tool", {})
    tool_output = tool_state.get("tool_output", {})
    tool_success = tool_state.get("tool_success", False)

    logger.info(f"  [NODE 9: DEBUG] intent='{intent}' | next_action='{next_action}' | tool_success={tool_success}")

    # Clean deterministic response ONLY if a transaction (reschedule/cancel) was executed ON THIS TURN!
    if next_action in ["reschedule", "cancel"] and tool_success and isinstance(tool_output, dict):
        data = tool_output.get("data", {})
        appt_id = data.get("appointment_id") or state["workflow"]["data"].get("appointment_id", "your appointment")
        
        if next_action == "reschedule" or data.get("status") == "rescheduled":
            new_date = data.get("new_date") or state["workflow"]["data"].get("date") or "requested date"
            new_time = data.get("new_time") or state["workflow"]["data"].get("time") or "requested time"
            reply = (
                f"Your appointment ({appt_id}) has been successfully rescheduled to {new_date} at {new_time}.\n\n"
                f"Thank you for choosing Gleneagles Hospitals!"
            )
            logger.info(f"  [NODE 9: GENERATE_RESPONSE] Formatted Clean Reschedule Reply for {appt_id}")
            return {
                "messages":     [AIMessage(content=reply)],
                "conversation": {**state["conversation"], "last_response": reply},
            }

        if next_action == "cancel" or data.get("status") == "cancelled":
            reply = (
                f"Your appointment ({appt_id}) has been successfully cancelled.\n\n"
                f"If you need to book a new appointment in the future, please feel free to reach out!"
            )
            logger.info(f"  [NODE 9: GENERATE_RESPONSE] Formatted Clean Cancel Reply for {appt_id}")
            return {
                "messages":     [AIMessage(content=reply)],
                "conversation": {**state["conversation"], "last_response": reply},
            }

    # Standard LLM response generation for inquiries, general chat, search results, and questions
    recent = "\n".join(f"{m.type}: {m.content}" for m in state["messages"][-4:])

    # GENERAL_QUERY Doctor Lookup: Find the specific doctor the user is asking about.
    # Priority order:
    #   1. Current message contains a doctor name → match from search_results cache
    #   2. Current message contains a pronoun (his/her/him/she/he) → resolve from recent history
    #   3. SQLite direct lookup using current message (fallback when cache is empty)
    search_results = list(state["runtime"].get("search_results", []))
    if intent == "GENERAL_QUERY":
        from langchain_core.messages import HumanMessage as _HumanMsg, AIMessage as _AIMsg

        # Extract the current user message (last human message only)
        current_user_msg = ""
        for m in reversed(state["messages"]):
            if isinstance(m, _HumanMsg):
                current_user_msg = m.content.lower()
                break

        # Helper: find a doctor in search_results whose name tokens appear in a text string
        def _find_doctor_in_text(text: str, candidates: list):
            text_lower = text.lower()
            for doc in candidates:
                doc_name = str(doc.get("doctor_name") or "")
                tokens = [t for t in doc_name.replace(".", "").split() if len(t) >= 4]
                if tokens and any(t.lower() in text_lower for t in tokens):
                    return doc
            return None

        # Step 1: Match doctor name directly from current user message in cache
        matched_doc = _find_doctor_in_text(current_user_msg, search_results)

        # Step 2: Context resolution — if no doctor name found in the current message,
        # try to resolve from recent conversation history.
        # This handles both:
        #   a) Pronouns: "what was his experience?" → find doctor in previous human message
        #   b) Bare follow-ups: "what was the consultation fee?" → same resolution
        if not matched_doc:
            previous_human_msgs = [m for m in reversed(state["messages"]) if isinstance(m, _HumanMsg)]
            for prev_msg in previous_human_msgs[1:]:   # skip [0] — that is the current message
                matched_doc = _find_doctor_in_text(prev_msg.content, search_results)
                if matched_doc:
                    logger.info(f"  [NODE 9: CONTEXT RESOLVED] '{current_user_msg}' → matched '{matched_doc.get('doctor_name')}' from conversation history")
                    break


        if matched_doc:
            # Use only the matched doctor, not the full list
            search_results = [matched_doc]
            logger.info(f"  [NODE 9: DOCTOR RESOLVED] GENERAL_QUERY → '{matched_doc.get('doctor_name')}'")

        else:
            # Step 3: SQLite fallback — search SQLite database for doctor
            # Checks current user message first, then scans previous human messages if no name in current message
            try:
                import sqlite3
                conn = sqlite3.connect("src/workflows/data/db/knowledge_base.db")
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT d.id, d.name, d.designation, d.qualifications, d.consultation_fee, d.experience_years, d.languages,
                           h.name, h.branch, h.city, d.speciality
                    FROM doctors d
                    LEFT JOIN hospitals h ON h.id = d.tenant_id OR h.tenant_id = d.tenant_id
                """)
                all_doctors = cursor.fetchall()
                conn.close()

                human_texts = [m.content.lower() for m in reversed(state["messages"]) if isinstance(m, _HumanMsg)]
                matched_row = None
                for text_to_check in human_texts:
                    for row in all_doctors:
                        doc_name = str(row[1] or "")
                        name_tokens = [t for t in doc_name.replace(".", "").split() if len(t) >= 4]
                        if name_tokens and any(t.lower() in text_to_check for t in name_tokens):
                            matched_row = row
                            break
                    if matched_row:
                        break

                # If no explicit doctor name found, dynamically match by token set intersection with designation & specialty
                if not matched_row:
                    best_score = 0
                    for text_to_check in human_texts:
                        text_tokens = set(t.lower() for t in re.findall(r'\b\w+\b', text_to_check) if len(t) >= 3)
                        for row in all_doctors:
                            desig_tokens = set(t.lower() for t in re.findall(r'\b\w+\b', str(row[2] or "")) if len(t) >= 3)
                            spec_tokens  = set(t.lower() for t in re.findall(r'\b\w+\b', str(row[10] or "")) if len(t) >= 3)
                            
                            desig_match = len(desig_tokens & text_tokens)
                            spec_match  = len(spec_tokens & text_tokens)
                            
                            if desig_match > 0:
                                score = desig_match * 2 + spec_match
                                if score > best_score:
                                    best_score = score
                                    matched_row = row
                        if matched_row and best_score >= 2:
                            break




                if matched_row:
                    row = matched_row
                    doc_name = str(row[1] or "")
                    h_name, h_branch, h_city = row[7], row[8], row[9]
                    full_branch = h_branch if (h_branch and len(h_branch) > len(str(h_name))) \
                        else f"{h_name}, {h_city}" if (h_name and h_city) else (h_name or h_city or "")
                    fee_val = row[4]
                    fee_str = f"₹{fee_val}" if (fee_val and not str(fee_val).startswith("₹")) else str(fee_val or "")
                    search_results = [{
                        "doctor_id":        row[0],
                        "doctor_name":      doc_name,
                        "designation":      row[2] or "",
                        "qualifications":   row[3] or "",
                        "consultation_fee": fee_str,
                        "experience_years": row[5],
                        "languages":        row[6] or "",
                        "department":       row[10] or "",
                        "branch":           full_branch,
                        "hospital_name":    full_branch,
                    }]
                    logger.info(f"  [NODE 9: SQLITE FALLBACK] Matched doctor: {doc_name} | fee={fee_str} | exp={row[5]}")
            except Exception as _sql_e:
                logger.warning(f"  [NODE 9: SQLITE FALLBACK FAILED] {_sql_e}")


    prompt = prompts.get(
        "response",
        tenant_id=state["tenant_id"],
        intent=state["conversation"]["intent"],
        workflow_data=state["workflow"]["data"],
        search_results=search_results,
        tool_output=state["tool"]["tool_output"],
        memory_summary=state["memory"]["summary"],
        needs_info=state["runtime"].get("needs_info", []),
        messages=recent,
    )

    reply_raw = llm.invoke([HumanMessage(content=prompt)])
    reply_text = reply_raw.content if hasattr(reply_raw, "content") else str(reply_raw)
    
    # Deterministic Spacing Normalizer: Enforce exact single-line breaks inside cards & 1 blank line between cards
    cleaned_reply = reply_text.replace("\r\n", "\n")

    
    # 1. Ensure SINGLE line break (\n) inside entire doctor block (Name -> Slots -> Morning -> Afternoon)
    cleaned_reply = re.sub(r'(\*\*[^\n]+\*\*)\n\s*\n+(Department:|Branch:|📅 Available Time Slots)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Department:[^\n]*)\n\s*\n+(Branch:|📅 Available Time Slots)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Branch:[^\n]*)\n\s*\n+(📅 Available Time Slots)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(📅 Available Time Slots[^\n]*)\n\s*\n+(Morning:|Afternoon:|Evening:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Morning:[^\n]*)\n\s*\n+(Afternoon:|Evening:)', r'\1\n\2', cleaned_reply)
    cleaned_reply = re.sub(r'(Afternoon:[^\n]*)\n\s*\n+(Evening:)', r'\1\n\2', cleaned_reply)


    # 2. Collapse any 3+ newlines to max 2 newlines (\n\n) for card separation
    cleaned_reply = re.sub(r'\n{3,}', '\n\n', cleaned_reply).strip()

    logger.info(f"  [NODE 9: GENERATE_RESPONSE] Generated Cleaned Reply: '{cleaned_reply[:100]}...'")
    return {
        "messages":     [AIMessage(content=cleaned_reply)],
        "conversation": {**state["conversation"], "last_response": cleaned_reply},
        "runtime":      {**state["runtime"], "search_results": search_results},
    }

