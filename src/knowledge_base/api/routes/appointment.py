"""
/appointment routes — AI-powered appointment booking assistant.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends

from src.knowledge_base.api.dependencies import get_graphrag_engine
from src.knowledge_base.query.graphrag_engine import GraphRAGEngine, QueryIntent

router = APIRouter(prefix="/appointment", tags=["appointment"])


class BookingRequest(BaseModel):
    message: str                       # Free-form user message
    session_id: Optional[str] = None   # Optional conversation session ID
    language: Optional[str] = None     # Preferred language filter
    hospital_id: Optional[str] = None  # Constrain to specific hospital
    tenant_id: Optional[str] = None    # Tenant filter (e.g. 'gleneagles', 'inventaa')


class BookingResponse(BaseModel):
    intent: str
    ai_response: str
    suggested_doctors: list[dict]
    booking_links: list[dict]
    next_steps: list[str]


@router.post("/assist", response_model=BookingResponse)
async def appointment_assistant(
    req: BookingRequest,
    engine: GraphRAGEngine = Depends(get_graphrag_engine),
):
    """
    Main conversational endpoint for the appointment booking AI.

    Accepts a natural language message and returns:
    - AI-generated response guiding the user
    - List of relevant doctors
    - Direct booking links
    - Clear next steps
    """
    result = await engine.query(req.message, tenant_id=req.tenant_id)

    next_steps = _build_next_steps(result.intent, result.booking_links, req.tenant_id)

    return BookingResponse(
        intent=result.intent,
        ai_response=result.response,
        suggested_doctors=result.doctors,
        booking_links=result.booking_links,
        next_steps=next_steps,
    )


@router.get("/quick-book/{doctor_id}")
async def quick_book(
    doctor_id: str,
    engine: GraphRAGEngine = Depends(get_graphrag_engine),
):
    """
    Quick booking context for a known doctor ID.
    Returns all data an AI agent needs to complete a booking.
    """
    result = await engine.query(f"Book appointment with doctor {doctor_id}")
    ctx = next(
        (d for d in result.doctors if d.get("doctor_id") == doctor_id
         or d.get("id") == doctor_id),
        result.doctors[0] if result.doctors else {},
    )
    return {
        "doctor_id": doctor_id,
        "appointment_context": ctx,
        "booking_url": ctx.get("booking_url") or ctx.get("profile_url"),
        "instructions": result.response,
    }


def _build_next_steps(intent: QueryIntent, booking_links: list[dict], tenant_id: Optional[str] = None) -> list[str]:
    """Generate actionable next steps based on intent."""
    from src.knowledge_base.config import get_tenant_config
    tc = get_tenant_config(tenant_id)

    if intent == QueryIntent.BOOK_APPOINTMENT and booking_links:
        link = booking_links[0]
        fee_line = (
            f"Consultation fee: {tc.currency_symbol}{int(link['fee'])} (if applicable)"
            if link.get("fee") else "Check fee at reception"
        )
        steps = [
            f"Visit the booking page: {link.get('booking_url', f'the {tc.brand_name} website')}",
            "Select your preferred date and time slot",
            "Fill in your personal details and reason for visit",
            "Confirm your appointment and note the reference number",
            fee_line,
        ]
    elif intent == QueryIntent.GET_DOCTOR_INFO:
        steps = [
            "Review the doctor's full profile via the profile URL",
            "Check available appointment slots",
            f"Call {tc.brand_name} to confirm availability",
        ]
    else:
        steps = [
            "Review the suggested doctors above",
            "Click a booking link to schedule your appointment",
        ]
        if tc.contact_phone:
            steps.append(f"Or call {tc.brand_name}: {tc.contact_phone}")
            steps.append(f"For emergencies: {tc.contact_phone} (24x7)")
    return steps
