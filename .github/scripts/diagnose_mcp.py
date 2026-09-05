import asyncio
import json

import mcp
from mcp.server.mcpserver.exceptions import (
    UnexpectedToolError,
    ToolError,
)
from vedit import mcp_server as srv


async def main():
    print("===== MCP ERROR SEMANTICS CONTROLLED EXPERIMENT =====")
    print("MCP version:", getattr(mcp, "__version__", "unknown"))
    print("MCP module:", mcp.__file__)
    print()

    try:
        result = await srv.mcp.call_tool(
            "add_clip",
            {"media": "x"},
        )

        print("CALL RETURNED NORMALLY")
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

        print()
        print("CLASSIFICATION: NORMAL RETURN")
        return

    except UnexpectedToolError as exc:
        print("EXCEPTION TYPE:", type(exc).__name__)
        print("EXCEPTION MODULE:", type(exc).__module__)
        print("EXCEPTION MESSAGE:", str(exc))
        print("EXCEPTION REPR:", repr(exc))
        print()

        cause = exc.__cause__

        print("CAUSE TYPE:", type(cause).__name__ if cause else None)
        print(
            "CAUSE MODULE:",
            type(cause).__module__ if cause else None,
        )
        print(
            "CAUSE MESSAGE:",
            str(cause) if cause else None,
        )
        print(
            "CAUSE REPR:",
            repr(cause) if cause else None,
        )

        print()
        print(
            "IS ToolError:",
            isinstance(exc, ToolError),
        )
        print(
            "CAUSE IS ToolError:",
            isinstance(cause, ToolError) if cause else False,
        )
        print(
            "CAUSE IS UnexpectedToolError:",
            isinstance(cause, UnexpectedToolError)
            if cause
            else False,
        )

        print()
        print("CLASSIFICATION: UNEXPECTED_TOOL_ERROR")
        print(
            "INTERPRETATION: MCPServer.call_tool() capturou "
            "uma exceção interna da ferramenta e a encapsulou."
        )
        print(
            "NEXT QUESTION: verificar se a causa original é "
            "EditError e se o comportamento coincide com o contrato MCP 2.x."
        )


asyncio.run(main())
