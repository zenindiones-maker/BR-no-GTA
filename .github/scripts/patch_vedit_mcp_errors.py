from pathlib import Path

p = Path("backend/vedit/mcp_server.py")
s = p.read_text()

old_import = "from mcp.server.mcpserver import Image, MCPServer"
new_import = (
    "from mcp.server.mcpserver import Image, MCPServer\n"
    "from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError"
)

if old_import not in s:
    raise SystemExit("ERRO: import MCPServer esperado não encontrado.")

if "class VeditMCPServer(MCPServer):" in s:
    raise SystemExit("ERRO: patch MCP já aplicado.")

old_server = """mcp = MCPServer(
    name="vedit",
    version="0.1.0",
    instructions=ISTRUZIONI,
)"""

new_server = """class VeditMCPServer(MCPServer):
    \"\"\"MCP server with Vedit domain-error semantics.\"\"\"

    async def call_tool(self, name, arguments, context=None):
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError as exc:
            cause = exc.__cause__

            if isinstance(cause, EditError):
                raise ToolError(str(cause)) from cause

            raise


mcp = VeditMCPServer(
    name="vedit",
    version="0.1.0",
    instructions=ISTRUZIONI,
)"""

if old_server not in s:
    raise SystemExit("ERRO: bloco MCPServer esperado não encontrado.")

s = s.replace(old_import, new_import, 1)
s = s.replace(old_server, new_server, 1)

p.write_text(s)

print("===== VEDIT MCP PATCH =====")
print("EditError -> ToolError boundary aplicado.")
print("UnexpectedToolError continua reservado para falhas inesperadas.")
print("===== END VEDIT MCP PATCH =====")
