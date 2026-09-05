import asyncio
import json

import mcp
from mcp.types import CallToolResult
from mcp.server.mcpserver.exceptions import ToolError
from vedit import mcp_server as srv


async def main():
    print("===== MCP ERROR SEMANTICS =====")
    print("MCP version:", getattr(mcp, "__version__", "unknown"))
    print("MCP module:", mcp.__file__)
    print()

    try:
        result = await srv.mcp.call_tool(
            "add_clip",
            {"media": "x"},
        )

        print("Result type:", type(result).__name__)
        print("Result:", result)
        print("is_error:", getattr(result, "is_error", None))
        print(
            "structured_content:",
            getattr(result, "structured_content", None),
        )

        content = getattr(result, "content", None) or []

        texts = [
            getattr(item, "text", None)
            for item in content
            if getattr(item, "text", None) is not None
        ]

        print(
            "content texts:",
            json.dumps(texts, ensure_ascii=False),
        )

        assert isinstance(result, CallToolResult)
        assert result.is_error is True
        assert texts
        assert "Error executing tool add_clip" in texts[0]

        print()
        print(
            "PASS: MCP 2.x representa o erro como "
            "CallToolResult(is_error=True)."
        )
        print(
            "PASS: a mensagem semântica do Vedit permanece "
            "disponível no resultado."
        )

    except ToolError as exc:
        print("UNEXPECTED DIRECT ToolError:", repr(exc))
        raise


asyncio.run(main())
