from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PLAYWRIGHT_MCP_VERSION = "0.0.82"
SAFE_TOOL_MAP = {
    "navigate": "browser_navigate",
    "snapshot": "browser_snapshot",
    "click": "browser_click",
    "hover": "browser_hover",
    "type": "browser_type",
    "press_key": "browser_press_key",
    "resize": "browser_resize",
    "screenshot": "browser_take_screenshot",
    "console_messages": "browser_console_messages",
    "network_requests": "browser_network_requests",
    "wait_for": "browser_wait_for",
    "tabs": "browser_tabs",
    "close": "browser_close",
}
FORBIDDEN_TOOLS = {
    "browser_run_code_unsafe",
    "browser_evaluate",
    "browser_file_upload",
    "browser_drop",
    "browser_route",
    "browser_network_state_set",
    "browser_storage_state",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/-]+=*)"),
    re.compile(
        r"(?i)((?:api[_-]?key|token|secret|cookie|set-cookie)\s*[:=]\s*)([^\s,;]+)"
    ),
)
MEDIA_REF_PATTERNS = (
    re.compile(r'button\s+"Media"[^\n]*\[ref=([^\]]+)\]', re.I),
    re.compile(r'\[ref=([^\]]+)\][^\n]*button[^\n]*"Media"', re.I),
)


class ExplorationPolicyError(RuntimeError):
    pass


@dataclass
class Budget:
    max_actions: int
    max_tabs: int
    max_screenshots: int
    max_navigations: int
    actions: int = 0
    screenshots: int = 0
    navigations: int = 0

    def charge(self, operation: str) -> None:
        if self.actions >= self.max_actions:
            raise ExplorationPolicyError("MAX_BROWSER_ACTIONS_EXCEEDED")
        if operation == "navigate":
            if self.navigations >= self.max_navigations:
                raise ExplorationPolicyError("MAX_NAVIGATIONS_EXCEEDED")
            self.navigations += 1
        if operation == "screenshot":
            if self.screenshots >= self.max_screenshots:
                raise ExplorationPolicyError("MAX_SCREENSHOTS_EXCEEDED")
            self.screenshots += 1
        self.actions += 1


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def redact(text: str) -> str:
    value = str(text or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda match: match.group(1) + "[REDACTED]", value)
    return value


def text_from_result(result: Any) -> str:
    chunks: list[str] = []
    for item in getattr(result, "content", ()) or ():
        text_value = getattr(item, "text", None)
        if text_value is not None:
            chunks.append(str(text_value))
    structured = getattr(result, "structured_content", None)
    if structured:
        chunks.append(json.dumps(structured, ensure_ascii=False, sort_keys=True))
    return redact("\n".join(chunks))


def content_address_file(source: Path, artifact_root: Path) -> dict[str, Any]:
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    suffix = source.suffix.lower() or ".bin"
    artifact_root.mkdir(parents=True, exist_ok=True)
    target = artifact_root / f"{digest}{suffix}"
    if not target.exists():
        shutil.copyfile(source, target)
    return {
        "source": str(source),
        "artifact_ref": f"artifact:browser-mcp/sha256/{digest}{suffix}",
        "sha256": digest,
        "size_bytes": len(raw),
    }


def normalize_request(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != "BrowserExplorationRequest/v1":
        raise ExplorationPolicyError("REQUEST_SCHEMA_INVALID")
    parsed = urlparse(str(raw.get("authorized_url") or ""))
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port not in {5173, 8760}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ExplorationPolicyError("UNAPPROVED_ORIGIN")
    allowed = raw.get("allowed_operations")
    if not isinstance(allowed, list) or not allowed:
        raise ExplorationPolicyError("ALLOWED_OPERATIONS_INVALID")
    if any(item not in SAFE_TOOL_MAP for item in allowed):
        raise ExplorationPolicyError("UNSAFE_OPERATION_REQUESTED")
    if raw.get("vision_allowed") is not False:
        raise ExplorationPolicyError("VISION_MODE_FORBIDDEN")
    if str(raw.get("network_scope") or "") != "first-party-loopback":
        raise ExplorationPolicyError("NETWORK_SCOPE_FORBIDDEN")
    return raw


def find_media_ref(snapshot: str) -> str:
    for pattern in MEDIA_REF_PATTERNS:
        match = pattern.search(snapshot)
        if match:
            return match.group(1)
    raise ExplorationPolicyError("MEDIA_CONTROL_REF_NOT_FOUND")


def assert_loopback_observations(text: str) -> None:
    for raw_url in re.findall(r"(?:https?|wss?)://[^\s<>()\"']+", text):
        parsed = urlparse(raw_url.rstrip(".,;"))
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ExplorationPolicyError("EXTERNAL_BROWSER_ORIGIN_OBSERVED")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ExplorationPolicyError("INVALID_BROWSER_ORIGIN_OBSERVED") from exc
        if port not in {5173, 8760}:
            raise ExplorationPolicyError("UNAPPROVED_BROWSER_PORT_OBSERVED")


def validate_pinned_mcp_executable(
    raw_path: str | os.PathLike[str],
    *,
    expected_cli: Path | None = None,
) -> Path:
    """Validate the npm bin shim without confusing its resolved target name.

    npm creates node_modules/.bin/playwright-mcp as a symlink to the pinned
    package cli.js. The shim name proves the requested command identity while
    the resolved target proves it cannot escape to another executable.
    """
    shim = Path(raw_path).absolute()
    if shim.name != "playwright-mcp" or not shim.is_file():
        raise ExplorationPolicyError("PINNED_MCP_EXECUTABLE_MISSING")
    try:
        resolved = shim.resolve(strict=True)
    except OSError as exc:
        raise ExplorationPolicyError(
            "PINNED_MCP_EXECUTABLE_MISSING"
        ) from exc

    expected = expected_cli or Path(
        "/tmp/browser-mcp/node_modules/@playwright/mcp/cli.js"
    )
    try:
        expected_resolved = expected.resolve(strict=True)
    except OSError as exc:
        raise ExplorationPolicyError(
            "PINNED_MCP_PACKAGE_CLI_MISSING"
        ) from exc
    if resolved != expected_resolved:
        raise ExplorationPolicyError(
            "PINNED_MCP_EXECUTABLE_TARGET_MISMATCH"
        )
    return shim


async def run_exploration(request: dict[str, Any], root: Path) -> dict[str, Any]:
    request = normalize_request(request)
    started = time.monotonic()
    evidence_dir = root / "evidence"
    operation_dir = root / "operations"
    artifact_root = root / "artifacts" / "sha256"
    output_dir = root / "mcp-output"
    for directory in (evidence_dir, operation_dir, artifact_root, output_dir):
        directory.mkdir(parents=True, exist_ok=True)

    executable = str(os.environ.get("BROWSER_EXECUTABLE_PATH") or "").strip()
    if not executable or not Path(executable).is_file():
        raise ExplorationPolicyError("PINNED_BROWSER_EXECUTABLE_MISSING")
    if str(os.environ.get("PLAYWRIGHT_MCP_VERSION") or "") != PLAYWRIGHT_MCP_VERSION:
        raise ExplorationPolicyError("PLAYWRIGHT_MCP_VERSION_MISMATCH")

    allowed_ops = tuple(request["allowed_operations"])
    allowed_tools = {SAFE_TOOL_MAP[item] for item in allowed_ops}
    if allowed_tools & FORBIDDEN_TOOLS:
        raise ExplorationPolicyError("FORBIDDEN_TOOL_ENTERED_ALLOWLIST")

    budget = Budget(
        max_actions=int(request["max_actions"]),
        max_tabs=int(request["max_tabs"]),
        max_screenshots=int(request["max_screenshots"]),
        max_navigations=int(request["max_navigations"]),
    )
    records: list[dict[str, Any]] = []
    console_text = ""
    network_text = ""

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "CI",
            "NPM_CONFIG_CACHE",
            "PLAYWRIGHT_BROWSERS_PATH",
        }
    }
    mcp_bin = validate_pinned_mcp_executable(
        os.environ.get(
            "PLAYWRIGHT_MCP_BIN",
            "/tmp/browser-mcp/node_modules/.bin/playwright-mcp",
        )
    )

    params = StdioServerParameters(
        command=str(mcp_bin),
        args=[
            "--headless",
            "--browser",
            "chromium",
            "--isolated",
            "--no-webmcp",
            "--block-service-workers",
            "--allowed-origins",
            "http://127.0.0.1:8760;http://127.0.0.1:5173",
            "--output-dir",
            str(output_dir),
            "--output-max-size",
            "20000000",
            "--codegen",
            "none",
            "--image-responses",
            "omit",
            "--snapshot-mode",
            "full",
            "--timeout-action",
            "5000",
            "--timeout-navigation",
            "15000",
            "--timeout-settle",
            "250",
            "--executable-path",
            executable,
        ],
        env=child_env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            available = {tool.name for tool in listed.tools}
            missing = sorted(allowed_tools - available)
            if missing:
                raise ExplorationPolicyError(
                    "REQUIRED_MCP_TOOLS_MISSING:" + ",".join(missing)
                )

            async def call(operation: str, arguments: dict[str, Any]) -> str:
                if operation not in allowed_ops:
                    raise ExplorationPolicyError(
                        f"OPERATION_NOT_AUTHORIZED:{operation}"
                    )
                tool = SAFE_TOOL_MAP[operation]
                if tool in FORBIDDEN_TOOLS:
                    raise ExplorationPolicyError(f"FORBIDDEN_TOOL:{tool}")
                if operation == "navigate":
                    if arguments != {"url": request["authorized_url"]}:
                        raise ExplorationPolicyError("ARBITRARY_NAVIGATION_BLOCKED")
                if operation == "wait_for":
                    if "time" in arguments:
                        raise ExplorationPolicyError("SLEEP_BASED_WAIT_FORBIDDEN")
                    if not (
                        str(arguments.get("text") or "").strip()
                        or str(arguments.get("textGone") or "").strip()
                    ):
                        raise ExplorationPolicyError("WAIT_REQUIRES_TEXT_CONDITION")
                if operation == "tabs" and arguments.get("action") != "list":
                    raise ExplorationPolicyError("TAB_MUTATION_NOT_ALLOWED_IN_PROOF")
                budget.charge(operation)
                result = await session.call_tool(tool, arguments=arguments)
                output = text_from_result(result)
                op_path = operation_dir / f"{budget.actions:02d}-{operation}.txt"
                op_path.write_text(output + "\n", encoding="utf-8")
                addressed = content_address_file(op_path, artifact_root)
                records.append({
                    "index": budget.actions,
                    "operation": operation,
                    "tool": tool,
                    "arguments": arguments,
                    "success": not bool(getattr(result, "is_error", False)),
                    "result_sha256": sha256(output.encode("utf-8")).hexdigest(),
                    "result_ref": addressed["artifact_ref"],
                })
                if getattr(result, "is_error", False):
                    raise ExplorationPolicyError(f"MCP_TOOL_FAILED:{tool}")
                return output

            width, height = (
                (1024, 768)
                if request["viewport"] == "desktop-narrow"
                else (1440, 900)
            )
            await call("navigate", {"url": request["authorized_url"]})
            await call("resize", {"width": width, "height": height})
            await call("wait_for", {"text": "VEDIT"})
            snapshot_text = await call("snapshot", {})
            media_ref = find_media_ref(snapshot_text)
            await call(
                "click",
                {
                    "element": "Media panel button from accessibility snapshot",
                    "target": media_ref,
                },
            )
            await call("snapshot", {})
            if "screenshot" in allowed_ops:
                await call(
                    "screenshot",
                    {
                        "type": "png",
                        "fullPage": False,
                        "scale": "css",
                    },
                )
            console_text = await call(
                "console_messages",
                {"level": "error", "all": True},
            )
            network_text = await call(
                "network_requests",
                {"static": False},
            )
            tabs_text = await call("tabs", {"action": "list"})
            assert_loopback_observations(tabs_text)
            assert_loopback_observations(network_text)
            tab_count = max(
                1,
                len(
                    [
                        line
                        for line in tabs_text.splitlines()
                        if line.strip().startswith("-")
                    ]
                ),
            )
            if tab_count > budget.max_tabs:
                raise ExplorationPolicyError("MAX_BROWSER_TABS_EXCEEDED")
            await call("close", {})

    evidence: list[dict[str, Any]] = []
    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        if artifact_root in source.parents:
            continue
        if source.name == "browser-exploration-evidence.json":
            continue
        if source.stat().st_size > 20_000_000:
            raise ExplorationPolicyError("EVIDENCE_FILE_TOO_LARGE")
        evidence.append(content_address_file(source, artifact_root))

    payload = {
        "schema": "BrowserExplorationEvidence/v1",
        "authority": "NONE",
        "mission_id": request["mission_id"],
        "plan_id": request.get("plan_id") or "",
        "task_id": request["task_id"],
        "candidate_sha": request["candidate_sha"],
        "authorized_url": request["authorized_url"],
        "scenario_goal": request["scenario_goal"],
        "allowed_operations": list(allowed_ops),
        "playwright_mcp_version": PLAYWRIGHT_MCP_VERSION,
        "mcp_python_sdk_version": importlib.metadata.version("mcp"),
        "browser_name": "chromium",
        "browser_version": str(os.environ.get("BROWSER_VERSION") or "unknown"),
        "node_version": str(os.environ.get("NODE_VERSION") or ""),
        "os_environment": {
            "platform": platform.system().lower(),
            "release": platform.release(),
            "arch": platform.machine(),
        },
        "isolated_context": True,
        "personal_profile_used": False,
        "webmcp_enabled": False,
        "unsafe_code_enabled": False,
        "browser_evaluate_enabled": False,
        "vision_fallback_used": False,
        "downloads_used": False,
        "uploads_used": False,
        "page_content_trust": "UNTRUSTED_DATA",
        "page_content_can_change_authority": False,
        "page_content_can_expand_tools": False,
        "operation_records": records,
        "action_count": budget.actions,
        "navigation_count": budget.navigations,
        "screenshot_count": budget.screenshots,
        "tab_count": tab_count,
        "budgets": {
            "max_actions": budget.max_actions,
            "max_tabs": budget.max_tabs,
            "max_screenshots": budget.max_screenshots,
            "max_navigations": budget.max_navigations,
            "max_wall_clock_seconds": int(request["timeout_seconds"]),
        },
        "console_error_observation_sha256": sha256(
            console_text.encode("utf-8")
        ).hexdigest(),
        "network_observation_sha256": sha256(
            network_text.encode("utf-8")
        ).hexdigest(),
        "evidence_refs": [item["artifact_ref"] for item in evidence],
        "mcp_exploration_used": True,
        "result": "OBSERVATION_COMPLETE",
        "metrics": {
            "browser_mcp_explorations_total": 1,
            "browser_mcp_unsafe_requests_blocked_total": 0,
            "browser_mcp_wall_ms": round((time.monotonic() - started) * 1000),
        },
    }
    payload["content_sha256"] = sha256(canonical_bytes(payload)).hexdigest()
    target = evidence_dir / "browser-exploration-evidence.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


async def async_main() -> int:
    raw = json.load(sys.stdin)
    root = Path(
        os.environ.get(
            "BROWSER_MCP_EVIDENCE_DIR",
            "browser-qa/mcp-evidence",
        )
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        result = await asyncio.wait_for(
            run_exploration(raw, root),
            timeout=int(raw.get("timeout_seconds") or 90),
        )
    except asyncio.TimeoutError:
        print(
            json.dumps({
                "schema": "BrowserExplorationFailure/v1",
                "failure_class": "BROWSER_EXPLORATION_BUDGET_EXCEEDED",
                "authority": "NONE",
            })
        )
        return 2
    except Exception as exc:
        print(
            json.dumps({
                "schema": "BrowserExplorationFailure/v1",
                "failure_class": type(exc).__name__,
                "error": redact(str(exc))[:1000],
                "authority": "NONE",
            })
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
