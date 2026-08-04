"""
registry.py — ToolRegistry

Central router. The LangGraph agent ONLY calls route().
It never imports DoctorSearchTool or AppointmentTool directly.

On register() → tool advertises its capabilities → registry builds the map.
On route()    → registry finds the right tool by operation automatically.

Usage:
    registry = ToolRegistry()
    registry.register(DoctorSearchTool())
    registry.register(AppointmentTool())

    response = registry.route(request)   # agent always uses this
"""

from src.tools.base import BaseTool
from src.tools.models import ToolRequest, ToolResponse


class ToolRegistry:
    """Routes requests by operation. Agent never picks a tool by name."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}          # tool name → tool instance
        self._capability_map: dict[str, str] = {}      # operation → tool name

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool. Automatically indexes all its capabilities.
        Adding a new tool = just call register(). Registry needs no changes.
        """
        self._tools[tool.name] = tool
        for operation in tool.capabilities:
            self._capability_map[operation] = tool.name

    def route(self, request: ToolRequest) -> ToolResponse:
        """
        The ONLY public method the agent calls.
        Finds which registered tool owns request.operation and runs it.
        """
        tool_name = self._capability_map.get(request.operation)
        if not tool_name:
            return ToolResponse.fail(
                error=f"No tool handles operation '{request.operation}'.",
                message=f"Unknown operation '{request.operation}'. Known: {list(self._capability_map.keys())}",
            )
        return self._tools[tool_name].execute(request)

    def list_tools(self) -> list[str]:
        """All registered tool names."""
        return list(self._tools.keys())

    def list_capabilities(self) -> dict[str, str]:
        """All known operations and which tool handles each one."""
        return dict(self._capability_map)
