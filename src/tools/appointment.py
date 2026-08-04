"""
appointment.py — AppointmentTool

Calls the Workflows API and returns a ToolResponse.
All URLs come from src/tools/config.py — nothing hardcoded here.

Capabilities: "availability", "book", "reschedule", "cancel"
  GET  /appointments/availability
  POST /appointments/book
  POST /appointments/reschedule
  POST /appointments/cancel
"""

import logging
import requests
from src.tools.base import BaseTool
from src.tools.config import APPOINTMENT_ENDPOINTS, REQUEST_TIMEOUT
from src.tools.models import ToolRequest, ToolResponse

logger = logging.getLogger("agent_tools")


class AppointmentTool(BaseTool):
    """Handles all appointment operations. One execute() — operation routes internally."""

    def __init__(self):
        self._dispatch = {
            "availability":       self._availability,              # GET /appointments/availability (single)
            "availability_batch": self._fetch_batch_availability,  # parallel per-doctor, fault-tolerant
            "book":               self._book,
            "reschedule":         self._reschedule,
            "cancel":             self._cancel,
        }

    @property
    def name(self) -> str:
        return "appointment"

    @property
    def description(self) -> str:
        return "Check slot availability, book, reschedule, or cancel a doctor appointment."

    @property
    def capabilities(self) -> set[str]:
        return set(self._dispatch.keys())

    def execute(self, request: ToolRequest) -> ToolResponse:
        handler = self._dispatch.get(request.operation)
        if not handler:
            return ToolResponse.fail(
                error=f"AppointmentTool does not support '{request.operation}'.",
                message=f"Supported: {list(self._dispatch.keys())}",
            )
        return handler(request.payload)

    # ── Private — one method per operation ────────────────────────────────

    def _availability(self, payload: dict) -> ToolResponse:
        """GET /appointments/availability — query params, 2-attempt retry on transient network errors."""
        url = APPOINTMENT_ENDPOINTS["availability"]
        logger.info(f"  [TERMINAL 3 -> TERMINAL 2: WORKFLOWS API | File: src/tools/appointment.py]")
        logger.info(f"    ↳ ROUTING HTTP GET -> {url} | Params: {payload}")
        for attempt in range(2):
            try:
                resp = requests.get(url, params=payload, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                slots = resp.json().get("slots", [])
                logger.info(f"  [TERMINAL 3 <- TERMINAL 2 OK] Returned {len(slots)} available slots.")
                return ToolResponse.ok(
                    data=slots,
                    message=f"Found {len(slots)} available slot(s).",
                    metadata={"doctor_id": payload.get("doctor_id"), "date": payload.get("date")},
                )
            except requests.RequestException as e:
                if attempt == 1:
                    logger.error(f"  [TERMINAL 3 -> TERMINAL 2 ERROR] availability failed after 2 attempts: {e}")
                    return ToolResponse.fail(error=f"Availability check failed: {e}")
                logger.warning(f"  [TERMINAL 3] availability attempt {attempt + 1} failed, retrying: {e}")

    def _fetch_batch_availability(self, payload: dict) -> ToolResponse:
        """
        Fetch availability for multiple doctors in parallel.
        Reuses _availability() — zero HTTP logic duplicated.

        Input:  { "doctors": [{"doctor_id": ..., "client_id": ...}, ...], "date": "YYYY-MM-DD" }
        Output: ToolResponse.data = { doctor_id: [slots], ... }  in original GraphRAG order.

        Guarantees:
          - Bounded thread pool (max 8 workers).
          - Per-doctor fault isolation: one failure returns [] without crashing the batch.
          - Retry logic is inside _availability() — two attempts per doctor.
          - Result order matches original GraphRAG doctor ranking.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        doctors = payload.get("doctors", [])
        date    = payload.get("date", "")

        if not doctors:
            return ToolResponse.ok(data={}, message="No doctors provided for batch availability.")

        def fetch_one(doctor: dict) -> tuple:
            doc_id = doctor.get("doctor_id") or doctor.get("sql_id") or doctor.get("id") or ""
            c_id   = doctor.get("client_id") or doctor.get("tenant_id") or payload.get("client_id") or "glh-chn"
            resp   = self._availability({
                "doctor_id": doc_id,
                "client_id": c_id,
                "date":      date,
            })
            slots = resp.data if (resp and resp.success and isinstance(resp.data, list)) else []
            return doc_id, slots

        # Step 1: Fetch all in parallel with bounded thread pool
        raw_results = {}
        max_workers = min(8, len(doctors))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, doc): doc for doc in doctors}
            for future in as_completed(futures):
                try:
                    doctor_id, slots = future.result()
                except Exception as exc:
                    doctor_id = futures[future]["doctor_id"]
                    slots     = []
                    logger.warning(f"  [AppointmentTool] Availability failed for {doctor_id}: {exc}")
                raw_results[doctor_id] = slots

        # Step 2: Restore original GraphRAG doctor ranking
        ordered_results = {
            doc["doctor_id"]: raw_results.get(doc["doctor_id"], [])
            for doc in doctors
        }

        with_slots = sum(1 for s in ordered_results.values() if s)
        logger.info(
            f"  [AppointmentTool] Batch done: {with_slots}/{len(ordered_results)} doctor(s) returned slots."
        )
        return ToolResponse.ok(
            data=ordered_results,
            message=f"Batch availability fetched for {len(ordered_results)} doctor(s).",
        )

    def _book(self, payload: dict) -> ToolResponse:
        """POST /appointments/book"""
        url = APPOINTMENT_ENDPOINTS["book"]
        logger.info(f"  [TERMINAL 3 -> TERMINAL 2: WORKFLOWS API | File: src/tools/appointment.py]")
        logger.info(f"    ↳ ROUTING HTTP POST -> {url} | Payload: {payload}")
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"  [TERMINAL 3 <- TERMINAL 2 OK] Booked Ref ID: {data.get('appointment_id')}")
            return ToolResponse.ok(
                data=data,
                message=f"Appointment booked. Reference ID: {data.get('appointment_id')}",
                metadata={"appointment_id": data.get("appointment_id")},
            )
        except requests.RequestException as e:
            logger.error(f"  [TERMINAL 3 -> TERMINAL 2 ERROR] {e}")
            return ToolResponse.fail(error=f"Booking failed: {e}")

    def _reschedule(self, payload: dict) -> ToolResponse:
        """POST /appointments/reschedule"""
        url = APPOINTMENT_ENDPOINTS["reschedule"]
        logger.info(f"  [TERMINAL 3 -> TERMINAL 2: WORKFLOWS API | File: src/tools/appointment.py]")
        logger.info(f"    ↳ ROUTING HTTP POST -> {url} | Payload: {payload}")
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"  [TERMINAL 3 <- TERMINAL 2 OK] Rescheduled Ref ID: {data.get('appointment_id')}")
            return ToolResponse.ok(
                data=data,
                message=data.get("message", f"Appointment {data.get('appointment_id')} rescheduled."),
                metadata={"appointment_id": data.get("appointment_id")},
            )
        except requests.RequestException as e:
            logger.error(f"  [TERMINAL 3 -> TERMINAL 2 ERROR] {e}")
            return ToolResponse.fail(error=f"Reschedule failed: {e}")

    def _cancel(self, payload: dict) -> ToolResponse:
        """POST /appointments/cancel"""
        url = APPOINTMENT_ENDPOINTS["cancel"]
        logger.info(f"  [TERMINAL 3 -> TERMINAL 2: WORKFLOWS API | File: src/tools/appointment.py]")
        logger.info(f"    ↳ ROUTING HTTP POST -> {url} | Payload: {payload}")
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"  [TERMINAL 3 <- TERMINAL 2 OK] Cancelled Ref ID: {data.get('appointment_id')}")
            return ToolResponse.ok(
                data=data,
                message=f"Appointment {data.get('appointment_id')} cancelled successfully.",
                metadata={"appointment_id": data.get("appointment_id")},
            )
        except requests.RequestException as e:
            logger.error(f"  [TERMINAL 3 -> TERMINAL 2 ERROR] {e}")
            return ToolResponse.fail(error=f"Cancel failed: {e}")
