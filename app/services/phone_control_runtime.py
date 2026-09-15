from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any


_ALLOWED_OPERATIONS = frozenset(
    {"ui", "list_apps", "tap", "swipe", "key", "start_app", "stop_app", "screenshot"}
)
_ALLOWED_KEYS = {
    "BACK": "back",
    "HOME": "home",
    "ENTER": "enter",
    "DPAD_UP": "dpad_up",
    "DPAD_DOWN": "dpad_down",
    "DPAD_LEFT": "dpad_left",
    "DPAD_RIGHT": "dpad_right",
}


def _emit_failure(stage: str, message: str, code: int) -> None:
    print(json.dumps({"success": False, "stage": stage, "error": message}))
    raise SystemExit(code)


async def _close_driver(driver: Any) -> None:
    """Close the HTTP client without depending on a private concrete client shape."""
    close = getattr(driver, "aclose", None)
    if callable(close):
        value = close()
        if hasattr(value, "__await__"):
            await value
        return
    close = getattr(driver, "close", None)
    if callable(close):
        value = close()
        if hasattr(value, "__await__"):
            await value
        return
    for name in ("client", "_client", "http", "_http"):
        client = getattr(driver, name, None)
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
            return


async def _run(request: dict[str, Any], token: str) -> dict[str, Any]:
    if request.get("backend") != "local-android-http":
        raise ValueError("Unexpected backend")
    operation = request.get("operation")
    if operation not in _ALLOWED_OPERATIONS:
        raise PermissionError("Operation not allowed")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("Invalid params")

    from mobilerun_core_local.driver.android import AndroidPortalHttpDriver

    driver = AndroidPortalHttpDriver(url=request["url"], token=token)
    try:
        await driver.connect()
        if operation == "ui":
            value = await driver.get_ui_tree()
            return {"ui": value}
        if operation == "list_apps":
            value = await driver.get_apps()
            return {"apps": value}
        if operation == "tap":
            await driver.tap(params["x"], params["y"])
            return dict(params)
        if operation == "swipe":
            await driver.swipe(
                params["x1"],
                params["y1"],
                params["x2"],
                params["y2"],
                duration_ms=params["duration_ms"],
            )
            return dict(params)
        if operation == "key":
            key = str(params["key"]).upper()
            button = _ALLOWED_KEYS.get(key)
            if button is None:
                raise PermissionError("Key not allowed")
            supported_buttons = getattr(driver, "supported_buttons", set())
            if button in supported_buttons or not supported_buttons:
                await driver.press_button(button)
            else:
                raise PermissionError("Key not supported by Portal driver")
            return {"key": key}
        if operation == "start_app":
            await driver.start_app(params["package"])
            return dict(params)
        if operation == "stop_app":
            await driver.stop_app(params["package"])
            return dict(params)
        if operation == "screenshot":
            shot = await driver.screenshot()
            return {"captured": bool(shot), "byte_length": len(shot) if shot else 0}
        raise PermissionError("Operation not allowed")
    finally:
        await _close_driver(driver)


def main() -> None:
    token = os.environ.get("MOBILERUN_PORTAL_TOKEN", "")
    if not token:
        _emit_failure("configuration", "Portal token missing", 2)

    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Invalid request")
    except Exception:
        _emit_failure("configuration", "Invalid runtime request", 2)

    if request.get("backend") != "local-android-http":
        _emit_failure("configuration", "Unexpected backend", 2)
    if request.get("operation") not in _ALLOWED_OPERATIONS:
        _emit_failure("policy", "Operation not allowed", 2)

    try:
        result = asyncio.run(_run(request, token))
    except PermissionError:
        _emit_failure("policy", "Phone operation not allowed", 4)
    except (KeyError, TypeError, ValueError):
        _emit_failure("operation", "Phone operation request invalid", 4)
    except Exception:
        # Deliberately do not echo driver/httpx exceptions: URLs, headers, or tokens
        # can be embedded in transport errors.
        _emit_failure("portal", "Phone Portal operation failed", 4)

    print(json.dumps({"success": True, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
