import inspect

import mcp
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


print("MCP module:", mcp.__file__)
print("MCP version:", getattr(mcp, "__version__", "unknown"))
print("MCPServer:", MCPServer)
print("ToolError:", ToolError)
print("call_tool signature:", inspect.signature(MCPServer.call_tool))
print("MCP SDK inspection complete.")
