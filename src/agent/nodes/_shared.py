"""
Shared singletons for all node files.
Created once at import time — reused across every request.
"""

from src.llm.client import LLMClient
from src.agent.memory import MemoryService
from src.agent.prompts.manager import PromptManager
from src.tools.registry import ToolRegistry
from src.tools.doctor_search import DoctorSearchTool
from src.tools.appointment import AppointmentTool

llm      = LLMClient()
memory   = MemoryService()
prompts  = PromptManager()
registry = ToolRegistry()
registry.register(DoctorSearchTool())
registry.register(AppointmentTool())
