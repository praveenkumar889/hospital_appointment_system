"""
doctor_search.py — DoctorSearchTool

Calls the Knowledge Base API and returns a ToolResponse.
All URLs come from src/tools/config.py — nothing hardcoded here.

Capability: "search"
  GET /search/doctors?q=...&n=...&tenant_id=...
"""

import logging
import requests
from src.tools.base import BaseTool
from src.tools.config import DOCTOR_ENDPOINTS, REQUEST_TIMEOUT
from src.tools.models import ToolRequest, ToolResponse

logger = logging.getLogger("agent_tools")


class DoctorSearchTool(BaseTool):
    """Searches doctors via GraphRAG (semantic + graph). One capability: search."""

    @property
    def name(self) -> str:
        return "doctor_search"

    @property
    def description(self) -> str:
        return "Search for doctors by specialty, language, location, or natural language query."

    @property
    def capabilities(self) -> set[str]:
        return {"search"}

    def execute(self, request: ToolRequest) -> ToolResponse:
        handler = {"search": self._search}.get(request.operation)
        if not handler:
            return ToolResponse.fail(error=f"DoctorSearchTool does not support '{request.operation}'.")
        return handler(request)

    # ── Private ────────────────────────────────────────────────────────────

    def _search(self, request: ToolRequest) -> ToolResponse:
        """GET /search/doctors — build params from payload and return ToolResponse."""
        query = request.payload.get("q") or request.payload.get("query", "")
        if not query:
            return ToolResponse.fail(error="A search query ('q') is required in payload.")

        params = {
            "q": query,
            "n": request.payload.get("n", 20),
        }
        if request.payload.get("tenant_id"):
            params["tenant_id"] = request.payload["tenant_id"]

        logger.info(f"  [TERMINAL 3 -> TERMINAL 1: KNOWLEDGE BASE API | File: src/tools/doctor_search.py]")
        logger.info(f"    ↳ ROUTING HTTP GET -> {DOCTOR_ENDPOINTS['search']} | Params: {params}")

        try:
            resp = requests.get(DOCTOR_ENDPOINTS["search"], params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            logger.error(f"  [TERMINAL 3 -> TERMINAL 1 ERROR] {e}")
            return ToolResponse.fail(error=f"Doctor search API error: {e}")

        raw_doctors = raw.get("doctors") or []
        formatted_doctors = []
        for d in raw_doctors:
            if isinstance(d, dict):
                raw_specs = d.get("specializations") or d.get("specialization") or []
                if isinstance(raw_specs, str):
                    raw_specs = [s.strip() for s in raw_specs.split(",") if s.strip()]
                cleaned_specs = []
                for s in (raw_specs if isinstance(raw_specs, list) else [str(raw_specs)]):
                    if s:
                        val = s.strip().title()
                        if val not in cleaned_specs:
                            cleaned_specs.append(val)
                hosps = d.get("hospitals") or []
                cities = d.get("cities") or []

                dept_val = cleaned_specs[0] if cleaned_specs else str(d.get("department") or d.get("specialty") or d.get("specialization") or "")
                specs_val = ", ".join(cleaned_specs) if cleaned_specs else str(d.get("specialization") or d.get("department") or "")
                hosp_val = d.get("branch_name") or d.get("location") or d.get("hospital_name") or (hosps[0] if hosps else "")
                city_val = d.get("city") or (cities[0] if cities else "")

                doc_record = {
                    "doctor_id":        str(d.get("doctor_id") or d.get("sql_id") or d.get("id") or ""),
                    "doctor_name":      str(d.get("doctor_name") or d.get("name") or ""),
                    "department":       str(dept_val),
                    "specialization":   str(specs_val),
                    "designation":      str(d.get("designation") or ""),
                    "qualifications":   str(d.get("qualifications") or ""),
                    "consultation_fee": str(d.get("consultation_fee") or ""),
                    "languages":        d.get("languages") if isinstance(d.get("languages"), list) else [],
                    "experience":       d.get("experience") or d.get("experience_years"),
                    "rating":           d.get("rating") or d.get("rating_score"),
                    "branch_name":      str(hosp_val),
                    "client_id":        str(d.get("client_id") or d.get("tenant_id") or ""),
                    "city":             str(city_val),
                }
                formatted_doctors.append({k: v for k, v in doc_record.items() if v is not None and v != ""})

        logger.info(f"  [TERMINAL 3 <- TERMINAL 1 OK] Returned {len(formatted_doctors)} rich doctor profile(s).")
        return ToolResponse.ok(
            data=formatted_doctors,
            message=raw.get("ai_response", f"Found {len(formatted_doctors)} doctor(s)."),
            metadata={
                "query":         query,
                "intent":        raw.get("intent"),
                "booking_links": raw.get("booking_links", []),
                "total":         len(formatted_doctors),
            },
        )
