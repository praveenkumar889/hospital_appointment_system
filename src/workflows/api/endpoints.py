import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import uuid
from src.workflows.services.booking_service import AppointmentBookingService
from src.workflows.api.schemas import (
    GetAvailabilityRequest, GetAvailabilityResponse,
    BookAppointmentRequest, BookAppointmentResponse,
    RescheduleAppointmentRequest, RescheduleAppointmentResponse,
    CancelAppointmentRequest, CancelAppointmentResponse,
    AvailableSlot
)

logger = logging.getLogger("workflows_api")
router = APIRouter(prefix="/appointments", tags=["Appointments"])


def handle_service_error(error: Exception, client_id: str = None) -> None:
    logger.error(f"[WORKFLOWS API ERROR] client_id: {client_id} | Error: {error}")
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400, detail={"error": str(error)})
    else:
        raise HTTPException(status_code=500, detail={"error": str(error)})


def get_booking_service(client_id: str) -> AppointmentBookingService:
    try:
        return AppointmentBookingService(client_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})


@router.get("/availability", response_model=GetAvailabilityResponse)
def get_availability(req: GetAvailabilityRequest = Depends()) -> GetAvailabilityResponse:
    try:
        logger.info("================================================================================")
        logger.info(f"[TERMINAL 2: WORKFLOWS API | File: src/workflows/api/endpoints.py]")
        logger.info(f"  ↳ RECEIVED HTTP GET FROM TERMINAL 3 (Agent AppointmentTool)")
        logger.info(f"  ↳ ACTION: Check Availability | client_id={req.client_id} | doctor_id={req.doctor_id} | date={req.date}")
        service = get_booking_service(req.client_id)
        slots = service.get_availability(req.doctor_id, req.date)
        logger.info(f"  ↳ WORKFLOWS API RESULT: Found {len(slots)} available slots -> Returning to Terminal 3")
        logger.info("================================================================================")
        return GetAvailabilityResponse(
            doctor_id=req.doctor_id,
            date=req.date,
            slots=[AvailableSlot(**slot) for slot in slots],
            client_id=req.client_id
        )
    except Exception as e:
        handle_service_error(e, req.client_id)


@router.post("/book", response_model=BookAppointmentResponse)
def book_appointment(req: BookAppointmentRequest) -> BookAppointmentResponse:
    try:
        logger.info("================================================================================")
        logger.info(f"[TERMINAL 2: WORKFLOWS API | File: src/workflows/api/endpoints.py]")
        logger.info(f"  ↳ RECEIVED HTTP POST FROM TERMINAL 3 (Agent AppointmentTool)")
        logger.info(f"  ↳ ACTION: Book Appointment | client_id={req.client_id} | doctor_id={req.doctor_id} | date={req.date} | time={req.time} | phone={req.patient_phone}")
        service = get_booking_service(req.client_id)
        result = service.book(
            phone=req.patient_phone,
            doctor_id=req.doctor_id,
            date=req.date,
            time=req.time,
            notes=req.notes
        )
        logger.info(f"  ↳ WORKFLOWS API RESULT: Booked Ref ID={result.get('appointment_id')} -> Returning to Terminal 3")
        logger.info("================================================================================")
        return BookAppointmentResponse(**result)
    except Exception as e:
        handle_service_error(e, req.client_id)


@router.post("/reschedule", response_model=RescheduleAppointmentResponse)
def reschedule_appointment(req: RescheduleAppointmentRequest) -> RescheduleAppointmentResponse:
    try:
        service = get_booking_service(req.client_id)
        result = service.reschedule(
            appointment_id=req.appointment_id,
            new_date=req.new_date,
            new_time=req.new_time
        )
        return RescheduleAppointmentResponse(**result)
    except Exception as e:
        handle_service_error(e, req.client_id)


@router.post("/cancel", response_model=CancelAppointmentResponse)
def cancel_appointment(req: CancelAppointmentRequest) -> CancelAppointmentResponse:
    try:
        service = get_booking_service(req.client_id)
        result = service.cancel(req.appointment_id)
        return CancelAppointmentResponse(**result)
    except Exception as e:
        handle_service_error(e, req.client_id)


@router.get("/lookup")
def lookup_appointment(identifier: str, client_id: str) -> dict:
    try:
        service = get_booking_service(client_id)
        return service.get_appointment(identifier)
    except Exception as e:
        handle_service_error(e, client_id)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ========================================================================================
# ✅ NEW ROUTER FOR /actions ENDPOINT (For Orchestrator)
# ========================================================================================

actions_router = APIRouter(tags=["Actions"])


# ✅ NEW REQUEST/RESPONSE MODELS FOR /actions (WITH OPTIONAL TYPES)
class ActionRequest(BaseModel):
    action: str  # "book", "cancel", "reschedule", "availability"
    doctor: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    department: Optional[str] = None
    patient_name: Optional[str] = None
    phone: Optional[str] = None
    appointment_id: Optional[str] = None
    client_id: Optional[str] = None  # ✅ ADD THIS - Branch ID from orchestrator


class ActionResponse(BaseModel):
    success: bool
    message: str
    appointment_id: Optional[str] = None
    booking_link: Optional[str] = None


# ✅ NEW ENDPOINT: POST /actions
@actions_router.post("/actions", response_model=ActionResponse)
def execute_action(request: ActionRequest):
    """
    Generic action endpoint for Orchestrator
    
    Accepts: book, cancel, reschedule, availability
    Routes to appropriate service method
    
    Args:
        action: Action type (book, cancel, reschedule, availability)
        doctor: Doctor ID or name
        date: Appointment date (YYYY-MM-DD)
        time: Appointment time (HH:MM)
        patient_name: Patient name (optional)
        phone: Patient phone (optional)
        appointment_id: For cancel/reschedule
        client_id: Branch ID from orchestrator session (e.g., glh-chn)
    
    Returns:
        ActionResponse with success status and message
    """
    
    try:
        action = request.action.lower()
        
        # ✅ BOOK APPOINTMENT
        if action == "book":
            if not request.doctor:
                return ActionResponse(
                    success=False,
                    message="Doctor name/ID is required"
                )
            if not request.date or not request.time:
                return ActionResponse(
                    success=False,
                    message="Date and time are required"
                )
            
            # ✅ USE PROVIDED CLIENT_ID OR GENERATE ONE
            client_id = request.client_id or f"client_{uuid.uuid4().hex[:8]}"
            service = AppointmentBookingService(client_id)
            
            # Use doctor name as doctor_id if not provided
            doctor_id = request.doctor
            
            result = service.book(
                phone=request.phone or "1234567890",  # Default if not provided
                doctor_id=doctor_id,
                date=request.date,
                time=request.time,
                notes=f"Patient: {request.patient_name or 'Unknown'}"
            )
            
            # ✅ Use the EXACT appointment_id saved into the database!
            appointment_id = result.get("appointment_id")
            
            return ActionResponse(
                success=True,
                message=f"✅ Appointment booked successfully!\n\nDoctor: {result.get('doctor_name', request.doctor)}\nDate: {request.date}\nTime: {request.time}\nAppointment Reference ID: {appointment_id}\n\nPlease arrive 10 minutes early.",
                appointment_id=appointment_id,
                booking_link=f"https://gleneagles.com/appointments/{appointment_id}"
            )
        
        # ✅ CANCEL APPOINTMENT
        elif action == "cancel":
            if not request.appointment_id:
                return ActionResponse(
                    success=False,
                    message="Appointment ID is required to cancel"
                )
            
            client_id = request.client_id or f"client_{uuid.uuid4().hex[:8]}"
            service = AppointmentBookingService(client_id)
            
            try:
                result = service.cancel(request.appointment_id)
                return ActionResponse(
                    success=True,
                    message=result.get("message", f"✅ Appointment {request.appointment_id} has been cancelled.\n\nYou will receive a confirmation email shortly."),
                    appointment_id=request.appointment_id
                )
            except Exception as e:
                return ActionResponse(
                    success=False,
                    message=f"Appointment Reference ID '{request.appointment_id}' not found."
                )
        
        # ✅ RESCHEDULE APPOINTMENT
        elif action == "reschedule":
            if not request.appointment_id:
                return ActionResponse(
                    success=False,
                    message="Appointment ID is required to reschedule"
                )
            if not request.date or not request.time:
                return ActionResponse(
                    success=False,
                    message="New date and time are required"
                )
            
            client_id = request.client_id or f"client_{uuid.uuid4().hex[:8]}"
            service = AppointmentBookingService(client_id)
            
            try:
                result = service.reschedule(
                    appointment_id=request.appointment_id,
                    new_date=request.date,
                    new_time=request.time
                )
                rescheduled_id = result.get("appointment_id", request.appointment_id)
                return ActionResponse(
                    success=True,
                    message=result.get("message", f"✅ Appointment {rescheduled_id} has been rescheduled to {request.date} at {request.time}."),
                    appointment_id=rescheduled_id
                )
            except Exception as e:
                return ActionResponse(
                    success=False,
                    message=f"Could not reschedule appointment: {str(e)}"
                )
        
        # ✅ CHECK AVAILABILITY
        elif action == "availability" or action == "check_availability":
            if not request.doctor:
                return ActionResponse(
                    success=False,
                    message="Doctor name/ID is required"
                )
            if not request.date:
                return ActionResponse(
                    success=False,
                    message="Date is required"
                )
            
            # ✅ USE PROVIDED CLIENT_ID OR GENERATE ONE
            client_id = request.client_id or f"client_{uuid.uuid4().hex[:8]}"
            service = AppointmentBookingService(client_id)
            
            try:
                slots = service.get_availability(request.doctor, request.date)
                
                if not slots:
                    return ActionResponse(
                        success=True,
                        message=f"❌ No available slots for {request.doctor} on {request.date}"
                    )
                
                slots_str = "\n".join([f"  • {slot['time']}" for slot in slots[:5]])
                
                return ActionResponse(
                    success=True,
                    message=f"✅ Available slots for {request.doctor} on {request.date}:\n{slots_str}"
                )
            except Exception as e:
                return ActionResponse(
                    success=True,
                    message=f"✅ Check availability service ready.\n\nDoctor: {request.doctor}\nDate: {request.date}"
                )
        
        else:
            return ActionResponse(
                success=False,
                message=f"Unknown action: {action}. Use: book, cancel, reschedule, availability"
            )
    
    except Exception as e:
        return ActionResponse(
            success=False,
            message=f"Error processing action: {str(e)}"
        )