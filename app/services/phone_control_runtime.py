from __future__ import annotations

import json
import os
import sys


def main() -> None:
    token = os.environ.get("MOBILERUN_PORTAL_TOKEN", "")
    if not token:
        print(json.dumps({"success": False, "stage": "configuration", "error": "Portal token missing"}))
        raise SystemExit(2)

    request = json.load(sys.stdin)
    if request.get("backend") != "local-android-http":
        print(json.dumps({"success": False, "stage": "configuration", "error": "Unexpected backend"}))
        raise SystemExit(2)

    try:
        from mobilerun import Mobilerun
        device = Mobilerun().connect(
            backend="local-android-http",
            url=request["url"],
            token=token,
        )
    except Exception:
        print(json.dumps({"success": False, "stage": "portal", "error": "Portal connection failed"}))
        raise SystemExit(3)

    operation = request["operation"]
    params = request.get("params") or {}
    try:
        if operation == "ui":
            value = device.ui_json() if callable(device.ui_json) else device.ui_json
            result = {"ui": value}
        elif operation == "list_apps":
            result = {"apps": device.list_apps()}
        elif operation == "tap":
            device.tap(params["x"], params["y"])
            result = dict(params)
        elif operation == "swipe":
            device.swipe(params["x1"], params["y1"], params["x2"], params["y2"], params["duration_ms"])
            result = dict(params)
        elif operation == "key":
            device.key(params["key"])
            result = dict(params)
        elif operation == "start_app":
            device.start_app(params["package"])
            result = dict(params)
        elif operation == "stop_app":
            device.stop_app(params["package"])
            result = dict(params)
        elif operation == "screenshot":
            shot = device.screenshot()
            result = {"captured": bool(shot)}
        else:
            raise ValueError("Operation not allowed")
    except Exception:
        print(json.dumps({"success": False, "stage": "operation", "error": "Phone operation failed"}))
        raise SystemExit(4)

    print(json.dumps({"success": True, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
