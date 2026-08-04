from .search import router as search_router
from .doctors import router as doctors_router
from .appointment import router as appointment_router

__all__ = ["search_router", "doctors_router", "appointment_router"]
