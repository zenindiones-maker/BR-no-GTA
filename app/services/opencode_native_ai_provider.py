from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Any

from app.services.ai_provider import AIProviderError, AIResponse
from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher
from app.services.performance_telemetry_service import emit_performance_event, utcnow_iso
from app.services.opencode_semantic_profile import (
    OPENCODE_SEMANTIC_AGENT_ID,
    OPENCODE_SEMANTIC_CONTRACT,
    OPENCODE_SEMANTIC_PROFILE_VERSION,
    semantic_profile_evidence,
    semantic_text_only_config_json,
    semantic_text_only_prompt,
)


OPENCODE_NATIVE_ARTIFACT_NAME = "opencode-native-result"
OPENCODE_NATIVE_WORKFLOW = "opencode-native-ai.yml"
OPENCODE_NATIVE_EXECUTOR_BINDING = (
    "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_OPENCODE_HANDOFF_PREFIX = "opencode-handoff"

def build_semantic_text_only_prompt(prompt: str) -> str:
    """Compatibility wrapper for the canonical semantic profile prompt."""
    return semantic_text_only_prompt(prompt)


def build_semantic_text_only_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Apply the dedicated OpenCode V2 text-only agent as an inline runtime override."""
    env = dict(os.environ if base_env is None else base_env)
    env["OPENCODE_CONFIG_CONTENT"] = semantic_text_only_config_json()
    return env


def _same_runner_cli_command(*, executor_model: str, prompt: str) -> tuple[list[str], str]:
    """Use the official OpenCode client path for opencode/* models.

    OpenCode documents `run` as the automation client. Standalone mode is the
    CI path for direct provider credentials; the OpenCode Console free/keyless
    tier performs client-admission checks and must stay on the official shared
    client/server path instead of a private standalone server.
    """
    shared_client = str(executor_model or "").startswith("opencode/")
    command = ["opencode", "run"]
    if not shared_client:
        command.append("--standalone")
    command.extend([
        "--model", executor_model,
        "--agent", OPENCODE_SEMANTIC_AGENT_ID,
        "--format", "json",
        build_semantic_text_only_prompt(prompt),
    ])
    return command, ("shared_client" if shared_client else "standalone")


def _immutable_dispatch_ref(
    *,
    repository: str,
    configured_ref: str,
    command_runner,
) -> tuple[str, str | None]:
    """Resolve one immutable workflow_dispatch tag to the exact parent GitHub SHA.

    Outside GitHub Actions, preserve the explicitly configured ref for local/unit
    callers. Inside Actions, never dispatch a semantic child on a moving branch.
    """
    source_sha = str(os.getenv("GITHUB_SHA") or "").strip().lower()
    in_actions = str(os.getenv("GITHUB_ACTIONS") or "").strip().lower() == "true"
    if not in_actions:
        return configured_ref, source_sha if _GIT_SHA_RE.fullmatch(source_sha) else None
    if not _GIT_SHA_RE.fullmatch(source_sha):
        raise OpenCodeNativeAIProviderError(
            "GitHub-hosted OpenCode execution requires an exact parent source SHA",
            details={"failure_code": "missing_parent_source_sha"},
        )

    tag = f"{_OPENCODE_HANDOFF_PREFIX}-{source_sha}"
    endpoint = f"repos/{repository}/git/ref/tags/{tag}"

    def read_target() -> str:
        value = command_runner([
            "gh", "api", endpoint, "--jq", ".object.sha",
        ]).strip().lower()
        if not _GIT_SHA_RE.fullmatch(value):
            raise OpenCodeNativeAIProviderError(
                "OpenCode handoff tag returned an invalid Git object SHA",
                details={"failure_code": "invalid_handoff_tag_target"},
            )
        return value

    try:
        target = read_target()
    except RuntimeError as exc:
        message = str(exc).lower()
        if "404" not in message and "not found" not in message and "does not exist" not in message:
            raise OpenCodeNativeAIProviderError(
                "Unable to verify OpenCode immutable handoff tag",
                details={"failure_code": "handoff_tag_lookup_failed"},
            ) from exc
        try:
            command_runner([
                "gh", "api", "--method", "POST",
                f"repos/{repository}/git/refs",
                "-f", f"ref=refs/tags/{tag}",
                "-f", f"sha={source_sha}",
                "--jq", ".object.sha",
            ])
        except RuntimeError as create_exc:
            # Parallel semantic calls may race to create the same commit tag.
            race = str(create_exc).lower()
            if "422" not in race and "already exists" not in race and "reference exists" not in race:
                raise OpenCodeNativeAIProviderError(
                    "Unable to create OpenCode immutable handoff tag",
                    details={"failure_code": "handoff_tag_create_failed"},
                ) from create_exc
        target = read_target()

    if target != source_sha:
        raise OpenCodeNativeAIProviderError(
            "OpenCode immutable handoff tag does not match the parent source SHA",
            details={"failure_code": "handoff_tag_sha_mismatch"},
        )
    return tag, source_sha



class OpenCodeNativeAIProviderError(AIProviderError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.safe_message = message
        self.details = dict(details or {})
        self.status_code = self.details.get("http_status")
        self.retryable = bool(self.details.get("retryable", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": "opencode",
            "model": self.details.get("canonical_model"),
            "code": self.details.get("failure_code", "opencode_native_failure"),
            "status_code": self.details.get("http_status"),
            "retryable": self.retryable,
            "message": self.safe_message,
            "error_type": type(self).__name__,
            "execution_ref": self.details.get("execution_ref"),
            "run_id": self.details.get("run_id"),
            "workflow_status": self.details.get("status"),
            "workflow_conclusion": self.details.get("conclusion"),
            "exit_code": self.details.get("exit_code"),
            "log_sha256": self.details.get("log_sha256"),
            "retry_count": int(self.details.get("retry_count") or 0),
            "profile_version": self.details.get("profile_version"),
            "profile_content_ref": self.details.get("profile_content_ref"),
            "tool_events": self.details.get("tool_events"),
            "tool_call_count": self.details.get("tool_call_count"),
            "tools_exposed": self.details.get("tools_exposed"),
            "semantic_agent": self.details.get("semantic_agent"),
            "semantic_profile_version": self.details.get("semantic_profile_version"),
            "semantic_contract": self.details.get("semantic_contract"),
            "semantic_text_only_pass": self.details.get("semantic_text_only_pass"),
            "error_events": self.details.get("error_events"),
            "safe_stderr_tail": self.details.get("safe_stderr_tail"),
            "parse_errors": self.details.get("parse_errors"),
            "stdout_ndjson_event_types": self.details.get("stdout_ndjson_event_types"),
            "finish_reason": self.details.get("finish_reason"),
            "answer_accumulated": self.details.get("answer_accumulated"),
            "cli_execution_mode": (
                (self.details.get("performance") or {}).get("cli_execution_mode")
                if isinstance(self.details.get("performance"), dict)
                else None
            ),
            "performance": self.details.get("performance"),
        }


def _sanitize_failed_log(log_text: str) -> dict[str, Any]:
    text = str(log_text or "")
    exit_codes = [
        int(value)
        for value in re.findall(r"exit code\s+(\d+)", text, flags=re.IGNORECASE)
    ]
    error_codes = []
    for pattern in (
        r"error_code[=:]\s*([A-Za-z0-9_.-]+)",
        r"OPENCODE_NATIVE_ERROR[=:]\s*([A-Za-z0-9_.-]+)",
    ):
        error_codes.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    result: dict[str, Any] = {
        "log_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "failure_code": (
            error_codes[-1] if error_codes else "opencode_native_workflow_failure"
        ),
    }
    if exit_codes:
        result["exit_code"] = exit_codes[-1]
    return result


def _json_candidate_is_complete(text: str) -> bool:
    normalized = str(text or "").strip()
    fence = chr(96) * 3
    if normalized.startswith(fence):
        lines = normalized.splitlines()
        if lines and lines[0].strip().startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    if normalized.startswith("json\n"):
        normalized = normalized[5:].strip()
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


def _recoverable_missing_finish_reason(
    *,
    answer: str,
    error_events: list[str],
    returncode: int | None,
) -> bool:
    if not answer.strip() or not returncode:
        return False
    protocol_error = any(
        "provider.invalid-output" in event
        and "stream ended without finish_reason" in event
        and ("status': 200" in event or '"status": 200' in event)
        for event in error_events
    )
    return protocol_error and _json_candidate_is_complete(answer)


def _retryable_missing_finish_reason_error(exc: "OpenCodeNativeAIProviderError") -> bool:
    events = [str(item) for item in (exc.details.get("error_events") or ())]
    return any(
        "provider.invalid-output" in event
        and "stream ended without finish_reason" in event
        and ("status': 200" in event or '"status": 200' in event)
        for event in events
    )


class OpenCodeNativeAIProvider:
    """Official OpenCode CLI executed on a bounded GitHub Actions runner."""

    def __init__(
        self,
        *,
        routing_decision,
        authorization,
        profile: dict[str, Any],
        repository: str | None = None,
        ref: str | None = None,
    ) -> None:
        self.routing_decision = routing_decision
        self.authorization = authorization
        self.profile = dict(profile)
        self.options = dict(profile.get("options") or {})
        self.executor_binding = OPENCODE_NATIVE_EXECUTOR_BINDING
        self.profile_version = str(profile["version"])
        self.profile_content_ref = str(profile["content_ref"])
        self.profile_checksum = str(profile["checksum"])
        self.last_performance_metrics: dict[str, Any] = {}
        self.repository = (
            repository
            or os.getenv("BR_OPENCODE_NATIVE_REPOSITORY")
            or os.getenv("GITHUB_ACTIONS_REPOSITORY")
            or "zenindiones-maker/BR-no-GTA"
        ).strip()
        self.ref = (
            ref
            or os.getenv("BR_OPENCODE_NATIVE_REF")
            or os.getenv("BR_OMNIROUTE_REF")
            or os.getenv("GITHUB_ACTIONS_RENDER_REF")
            or "main"
        ).strip()
        self.source_sha = (
            os.getenv("BR_OPENCODE_NATIVE_SOURCE_SHA")
            or os.getenv("GITHUB_SHA")
            or ""
        ).strip()
        if not self.repository or not self.ref:
            raise ValueError("OpenCode native GitHub repository/ref are required")
        if self.options.get("executor_kind") != "official_opencode_cli_github_actions":
            raise PermissionError("OpenCode native provider received a non-native profile")
        if routing_decision.selected_provider != "opencode":
            raise PermissionError("OpenCode native provider identity mismatch")
        if routing_decision.selected_model != self.options.get("canonical_model"):
            raise PermissionError("OpenCode native canonical model mismatch")

        command_runner = run_github_actions_command
        dispatcher = GitHubActionsDispatcher(command_runner)
        tracker = GitHubActionsRunTracker(command_runner)
        watcher = GitHubActionsRunWatcher(
            tracker,
            poll_interval=float(os.getenv("BR_OPENCODE_NATIVE_POLL_INTERVAL", "5")),
            timeout=float(os.getenv("BR_OPENCODE_NATIVE_RUN_TIMEOUT", "900")),
        )
        artifacts = GitHubActionsArtifactService(command_runner)
        self.command_runner = command_runner
        self.dispatcher = dispatcher
        self.watcher = watcher
        self.artifacts = artifacts
        self.artifact_root = Path(
            os.getenv(
                "BR_OPENCODE_NATIVE_ARTIFACT_ROOT",
                "runtime/opencode-native-artifacts",
            )
        )

    def _download_native_result_payload(self, run_id: int) -> dict[str, Any]:
        """Best-effort structured evidence retrieval, including failed workflow runs."""
        output_dir = self.artifact_root / str(run_id)
        try:
            self.artifacts.download(
                repository=self.repository,
                run_id=run_id,
                artifact_name=OPENCODE_NATIVE_ARTIFACT_NAME,
                output_dir=output_dir,
            )
        except Exception:
            return {}
        files = sorted(output_dir.rglob("result.json"))
        if len(files) != 1:
            return {}
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _generate_on_current_runner(
        self,
        *,
        prompt: str,
        canonical_model: str,
        executor_model: str,
        cli_version: str,
        attempt_count: int = 1,
    ) -> AIResponse:
        """Run the already-promoted official CLI in the current GitHub runner.

        The promotion benchmark executes this exact CLI successfully in the parent
        runner. Nested workflow dispatch is not an authority boundary and is
        avoided here because the upstream free tier rejects that child runtime.
        """
        if str(os.getenv("GITHUB_ACTIONS") or "").strip().lower() != "true":
            raise OpenCodeNativeAIProviderError(
                "Same-run OpenCode execution is allowed only on GitHub Actions",
                details={"failure_code": "same_runner_requires_github_actions"},
            )

        expected_sha = str(self.source_sha or os.getenv("GITHUB_SHA") or "").strip().lower()
        if not _GIT_SHA_RE.fullmatch(expected_sha):
            raise OpenCodeNativeAIProviderError(
                "Same-run OpenCode execution requires exact source SHA",
                details={"failure_code": "missing_parent_source_sha"},
            )
        observed_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip().lower()
        if observed_sha != expected_sha:
            raise OpenCodeNativeAIProviderError(
                "Same-run OpenCode source SHA mismatch",
                details={"failure_code": "semantic_source_sha_mismatch"},
            )

        version = subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip().split()[-1].lstrip("v")
        if version != cli_version:
            raise OpenCodeNativeAIProviderError(
                "Same-run OpenCode CLI version mismatch",
                details={"failure_code": "cli_version_mismatch"},
            )

        perf_started_at = utcnow_iso()
        provider_started_ns = time.perf_counter_ns()
        parts: list[str] = []
        tool_call_count = 0
        tool_events: list[dict[str, Any]] = []
        error_events: list[str] = []
        event_types: list[str] = []
        finish_reasons: list[str] = []
        parse_errors = 0
        event_count = 0
        parse_ns = 0
        first_event_ns = None
        first_text_ns = None
        last_event_ns = None
        process = None
        timed_out = threading.Event()
        stderr_text = ""
        stdout_log_hasher = sha256()

        with tempfile.TemporaryDirectory(prefix="br-opencode-") as tmp:
            stderr_path = Path(tmp) / "stderr.log"
            with stderr_path.open("w+", encoding="utf-8") as stderr_stream:
                cli_command, cli_execution_mode = _same_runner_cli_command(
                    executor_model=executor_model,
                    prompt=prompt,
                )
                process = subprocess.Popen(
                    cli_command,
                    stdout=subprocess.PIPE,
                    stderr=stderr_stream,
                    text=True,
                    bufsize=1,
                    cwd=tmp,
                    env=build_semantic_text_only_env(dict(os.environ)),
                )
                process_launched_ns = time.perf_counter_ns()

                def _kill_timeout() -> None:
                    timed_out.set()
                    if process is not None and process.poll() is None:
                        process.kill()

                timer = threading.Timer(300.0, _kill_timeout)
                timer.daemon = True
                timer.start()
                try:
                    if process.stdout is None:
                        raise OpenCodeNativeAIProviderError(
                            "OpenCode stdout pipe was not created",
                            details={"failure_code": "missing_stdout_pipe"},
                        )
                    for raw in process.stdout:
                        observed_ns = time.perf_counter_ns()
                        stdout_log_hasher.update(raw.encode("utf-8", errors="replace"))
                        if not raw.strip():
                            continue
                        parse_started_ns = time.perf_counter_ns()
                        try:
                            item = json.loads(raw)
                        except json.JSONDecodeError:
                            parse_errors += 1
                            parse_ns += time.perf_counter_ns() - parse_started_ns
                            continue
                        parse_ns += time.perf_counter_ns() - parse_started_ns
                        event_count += 1
                        if first_event_ns is None:
                            first_event_ns = observed_ns
                        last_event_ns = observed_ns
                        event_type = str(item.get("type") or "")
                        event_types.append(event_type or "<missing>")
                        if event_type in {"step_finish", "step-finish"}:
                            part = item.get("part") if isinstance(item.get("part"), dict) else {}
                            reason = (
                                item.get("finish_reason")
                                or item.get("reason")
                                or part.get("finish_reason")
                                or part.get("reason")
                            )
                            if reason not in (None, ""):
                                finish_reasons.append(str(reason))
                        if event_type in {"tool_use", "tool_call", "tool"}:
                            tool_call_count += 1
                            part = item.get("part") if isinstance(item.get("part"), dict) else {}
                            state = part.get("state") if isinstance(part.get("state"), dict) else {}
                            tool_events.append({
                                "event_type": event_type,
                                "tool": str(
                                    item.get("tool")
                                    or item.get("name")
                                    or part.get("tool")
                                    or part.get("name")
                                    or ""
                                )[:120],
                                "status": str(
                                    item.get("status")
                                    or part.get("status")
                                    or state.get("status")
                                    or ""
                                )[:80],
                            })
                        if event_type == "error":
                            candidate_error = item.get("error") or item.get("message") or item.get("data")
                            if candidate_error:
                                safe = re.sub(
                                    r"(?i)(authorization:|bearer\\s+|api[_-]?key|token=|sk-|ghp_|github_pat_)[^\\s,;]*",
                                    "[REDACTED]",
                                    str(candidate_error)[:1600],
                                )
                                error_events.append(safe)
                        if event_type == "text":
                            part = item.get("part") or {}
                            value = part.get("text")
                            if isinstance(value, str) and value:
                                if first_text_ns is None:
                                    first_text_ns = observed_ns
                                parts.append(value)
                    process.wait()
                finally:
                    timer.cancel()
                process_finished_ns = time.perf_counter_ns()
                stderr_stream.flush()
                stderr_stream.seek(0)
                stderr_text = stderr_stream.read()

        answer = "".join(parts).strip()
        if process is None:
            raise OpenCodeNativeAIProviderError(
                "OpenCode process was not created",
                details={"failure_code": "process_not_created"},
            )
        first_event_at = first_event_ns or process_finished_ns
        first_text_at = first_text_ns or first_event_at
        last_event_at = last_event_ns or first_event_at
        performance = {
            "cli_process_launch_ms": (process_launched_ns - provider_started_ns) / 1_000_000.0,
            "cli_process_startup_ms": (first_event_at - provider_started_ns) / 1_000_000.0,
            "model_first_token_ms": (first_text_at - first_event_at) / 1_000_000.0,
            "model_total_ms": (last_event_at - first_event_at) / 1_000_000.0,
            "json_parse_ms": parse_ns / 1_000_000.0,
            "process_teardown_ms": (process_finished_ns - last_event_at) / 1_000_000.0,
            "provider_total_ms": (process_finished_ns - provider_started_ns) / 1_000_000.0,
            "event_count": event_count,
            "stdout_ndjson_event_types": list(event_types),
            "finish_reason": (finish_reasons[-1] if finish_reasons else None),
            "answer_accumulated": bool(answer),
            "answer_length": len(answer),
            "cli_execution_mode": cli_execution_mode,
            "tool_call_count": tool_call_count,
            "parse_errors": parse_errors,
            "timed_out": timed_out.is_set(),
        }
        performance.update(semantic_profile_evidence())
        performance["tools_exposed"] = 0 if tool_call_count == 0 else tool_call_count
        performance["semantic_text_only_pass"] = (
            process.returncode == 0
            and bool(answer)
            and tool_call_count == 0
            and not timed_out.is_set()
        )
        self.last_performance_metrics = dict(performance)
        safe_stderr_lines = [
            line[:500]
            for line in stderr_text.splitlines()
            if not re.search(
                r"(authorization:|bearer |api_key|apikey|token=|sk-|ghp_|github_pat_)",
                line,
                flags=re.IGNORECASE,
            )
        ][-10:]
        protocol_recovered = _recoverable_missing_finish_reason(
            answer=answer,
            error_events=error_events,
            returncode=process.returncode,
        )
        performance["protocol_recovered"] = protocol_recovered
        failure_type = None
        if tool_call_count:
            failure_type = "semantic_tools_used"
        elif timed_out.is_set():
            failure_type = "provider_timeout"
        elif process.returncode != 0 and not protocol_recovered:
            failure_type = "provider_nonzero_exit"
        elif not answer:
            failure_type = "empty_response"
        emit_performance_event(
            stage="opencode.semantic.generate",
            category="AI_PROVIDER_TIME",
            started_at=perf_started_at,
            finished_at=utcnow_iso(),
            duration_ms=performance["provider_total_ms"],
            provider_wait_ms=performance["provider_total_ms"],
            retry_count=max(0, int(attempt_count) - 1),
            backoff_ms=0.0,
            attempt_count=max(1, int(attempt_count)),
            cache_hit=False,
            input_size=len(prompt.encode("utf-8")),
            output_size=len(answer.encode("utf-8")),
            provider="opencode",
            model=canonical_model,
            success=failure_type is None,
            failure_type=failure_type,
            metadata={
                **performance,
                **semantic_profile_evidence(),
                "tools_exposed": 0 if tool_call_count == 0 else tool_call_count,
                "error_events": error_events[-3:],
                "safe_stderr_tail": safe_stderr_lines[-3:],
            },
            started_monotonic_ns=provider_started_ns,
            finished_monotonic_ns=process_finished_ns,
            execution_id=self.authorization.execution_id,
            capability_id="ai.reasoning.text",
        )
        if tool_call_count:
            raise OpenCodeNativeAIProviderError(
                "Same-run semantic execution attempted tool use",
                details={
                    "failure_code": "semantic_tools_used",
                    "exit_code": process.returncode,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "semantic_agent": OPENCODE_SEMANTIC_AGENT_ID,
                    "semantic_profile_version": OPENCODE_SEMANTIC_PROFILE_VERSION,
                    "semantic_contract": OPENCODE_SEMANTIC_CONTRACT,
                    "semantic_text_only_pass": False,
                    "tool_call_count": tool_call_count,
                    "tools_exposed": tool_call_count,
                    "tool_events": tool_events[:8],
                    "error_events": error_events[-5:],
                    "safe_stderr_tail": safe_stderr_lines,
                    "performance": performance,
                },
            )
        if protocol_recovered:
            return AIResponse(
                text=answer,
                provider="opencode",
                model=canonical_model,
                finish_reason="missing_finish_reason_recovered_after_complete_json",
            )

        if process.returncode != 0 or not answer:
            safe_stderr = "\n".join(safe_stderr_lines)
            safe_cause = (
                error_events[-1][:600]
                if error_events
                else (safe_stderr_lines[-1][:600] if safe_stderr_lines else "no provider diagnostic")
            )
            raise OpenCodeNativeAIProviderError(
                (
                    "Governed same-run OpenCode execution failed; "
                    f"exit_code={process.returncode}; cause={safe_cause}"
                ),
                details={
                    "failure_code": "same_runner_native_execution_failed",
                    "exit_code": process.returncode,
                    "log_sha256": (
                        lambda digest: (
                            digest.update(b"\n"),
                            digest.update(safe_stderr.encode("utf-8", errors="replace")),
                            digest.hexdigest(),
                        )[-1]
                    )(stdout_log_hasher.copy()),
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "retry_count": max(0, int(attempt_count) - 1),
                    "attempt_count": max(1, int(attempt_count)),
                    "parse_errors": parse_errors,
                    "stdout_ndjson_event_types": list(event_types),
                    "finish_reason": (finish_reasons[-1] if finish_reasons else None),
                    "answer_accumulated": answer,
                    "tool_events": tool_events[:8],
                    "error_events": error_events[-5:],
                    "safe_stderr_tail": safe_stderr_lines,
                    "performance": performance,
                },
            )

        return AIResponse(
            text=answer,
            provider="opencode",
            model=canonical_model,
            finish_reason="stop",
        )

    def generate(self, prompt: str) -> AIResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AIProviderError("OpenCode prompt must be non-empty")

        canonical_model = str(self.options["canonical_model"])
        executor_model = str(self.options["executor_model"])
        cli_version = str(self.options["cli_version"])
        workflow = str(self.options.get("workflow") or OPENCODE_NATIVE_WORKFLOW)
        if str(os.getenv("BR_OPENCODE_NATIVE_EXECUTION_MODE") or "").strip() == "same_runner":
            try:
                return self._generate_on_current_runner(
                    prompt=prompt,
                    canonical_model=canonical_model,
                    executor_model=executor_model,
                    cli_version=cli_version,
                    attempt_count=1,
                )
            except OpenCodeNativeAIProviderError as exc:
                if not _retryable_missing_finish_reason_error(exc):
                    raise
                return self._generate_on_current_runner(
                    prompt=prompt,
                    canonical_model=canonical_model,
                    executor_model=executor_model,
                    cli_version=cli_version,
                    attempt_count=2,
                )
        dispatch_ref, parent_source_sha = _immutable_dispatch_ref(
            repository=self.repository,
            configured_ref=self.ref,
            command_runner=self.command_runner,
        )
        source_sha = str(self.source_sha or parent_source_sha or "").strip().lower()
        if parent_source_sha is not None and source_sha != parent_source_sha:
            raise OpenCodeNativeAIProviderError(
                "Configured OpenCode source SHA does not match the parent GitHub SHA",
                details={"failure_code": "semantic_source_sha_mismatch"},
            )
        dispatched = self.dispatcher.dispatch(
            repository=self.repository,
            workflow=workflow,
            ref=dispatch_ref,
            inputs={
                "mode": "opencode_native",
                "execution_id": self.authorization.execution_id,
                "provider": "opencode",
                "model": canonical_model,
                "prompt_b64": base64.b64encode(prompt.encode("utf-8")).decode("ascii"),
                "zero_cost_operation": "true",
                "source_sha": source_sha,
            },
        )
        watched = self.watcher.wait_for_completion(
            repository=self.repository,
            run_id=dispatched.run_id,
        )
        if not watched.succeeded:
            try:
                failed_log = self.command_runner([
                    "gh",
                    "run",
                    "view",
                    str(dispatched.run_id),
                    "--repo",
                    self.repository,
                    "--log-failed",
                ])
            except Exception:
                failed_log = ""
            artifact_payload = self._download_native_result_payload(dispatched.run_id)
            details = {
                "execution_ref": f"github-actions:{dispatched.run_id}",
                "run_id": dispatched.run_id,
                "status": watched.status,
                "conclusion": watched.conclusion,
                "canonical_model": canonical_model,
                "executor_model": executor_model,
                "profile_version": self.profile_version,
                "profile_content_ref": self.profile_content_ref,
                "retry_count": 0,
                "semantic_agent": artifact_payload.get("semantic_agent"),
                "semantic_profile_version": artifact_payload.get("semantic_profile_version"),
                "semantic_contract": artifact_payload.get("semantic_contract"),
                "semantic_text_only_pass": artifact_payload.get("semantic_text_only_pass"),
                "tool_call_count": artifact_payload.get("tool_call_count"),
                "tools_exposed": artifact_payload.get("tools_exposed"),
                "tool_events": artifact_payload.get("tool_events"),
                "error_events": artifact_payload.get("error_events"),
                "safe_stderr_tail": artifact_payload.get("safe_stderr"),
                **_sanitize_failed_log(failed_log),
            }
            raise OpenCodeNativeAIProviderError(
                "Governed OpenCode native execution failed",
                details=details,
            )

        output_dir = self.artifact_root / str(dispatched.run_id)
        self.artifacts.download(
            repository=self.repository,
            run_id=dispatched.run_id,
            artifact_name=OPENCODE_NATIVE_ARTIFACT_NAME,
            output_dir=output_dir,
        )
        files = sorted(output_dir.rglob("result.json"))
        if len(files) != 1:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result artifact is missing or ambiguous",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "invalid_result_artifact",
                },
            )
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result artifact is invalid",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "invalid_result_json",
                },
            ) from exc

        required = {
            "status",
            "provider",
            "canonical_model",
            "executor_model",
            "text",
            "cli_version",
            "runtime_identity",
            "elapsed_seconds",
            "fallback_occurred",
            "retry_count",
            "tool_call_count",
            "tools_exposed",
            "semantic_agent",
            "semantic_profile_version",
            "semantic_contract",
            "semantic_text_only_pass",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result is incomplete",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "incomplete_result",
                },
            )
        if payload["status"] != "EXECUTED":
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result did not succeed",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "non_executed_result",
                },
            )
        if payload["provider"] != "opencode":
            raise PermissionError("OpenCode native provider identity mismatch")
        if payload["canonical_model"] != canonical_model:
            raise PermissionError("OpenCode native canonical model mismatch")
        if payload["executor_model"] != executor_model:
            raise PermissionError("OpenCode native executor model mismatch")
        if payload["cli_version"] != cli_version:
            raise PermissionError("OpenCode native CLI version mismatch")
        if payload["fallback_occurred"] is not False:
            raise PermissionError("OpenCode native executor reported fallback")
        if payload["semantic_agent"] != OPENCODE_SEMANTIC_AGENT_ID:
            raise OpenCodeNativeAIProviderError(
                "OpenCode semantic executor used the wrong agent",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "semantic_agent_mismatch",
                    "semantic_agent": payload.get("semantic_agent"),
                    "semantic_profile_version": payload.get("semantic_profile_version"),
                },
            )
        if payload["semantic_profile_version"] != OPENCODE_SEMANTIC_PROFILE_VERSION:
            raise OpenCodeNativeAIProviderError(
                "OpenCode semantic profile version mismatch",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "semantic_profile_mismatch",
                    "semantic_agent": payload.get("semantic_agent"),
                    "semantic_profile_version": payload.get("semantic_profile_version"),
                },
            )
        if payload["semantic_contract"] != OPENCODE_SEMANTIC_CONTRACT:
            raise OpenCodeNativeAIProviderError(
                "OpenCode semantic contract mismatch",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "failure_code": "semantic_contract_mismatch",
                    "semantic_contract": payload.get("semantic_contract"),
                },
            )
        if (
            int(payload["tool_call_count"] or 0) != 0
            or int(payload["tools_exposed"] or 0) != 0
            or payload["semantic_text_only_pass"] is not True
        ):
            raise OpenCodeNativeAIProviderError(
                "OpenCode semantic execution violated zero-tool contract",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "semantic_tools_used",
                    "semantic_agent": payload.get("semantic_agent"),
                    "semantic_profile_version": payload.get("semantic_profile_version"),
                    "semantic_contract": payload.get("semantic_contract"),
                    "semantic_text_only_pass": payload.get("semantic_text_only_pass"),
                    "tool_call_count": payload.get("tool_call_count"),
                    "tools_exposed": payload.get("tools_exposed"),
                    "tool_events": payload.get("tool_events"),
                    "error_events": payload.get("error_events"),
                    "safe_stderr_tail": payload.get("safe_stderr"),
                },
            )
        self.last_performance_metrics = {
            "tool_call_count": int(payload["tool_call_count"] or 0),
            "tools_exposed": int(payload["tools_exposed"] or 0),
            "semantic_text_only_pass": bool(payload["semantic_text_only_pass"]),
            "semantic_agent": payload["semantic_agent"],
            "semantic_profile_version": payload["semantic_profile_version"],
            "elapsed_seconds": payload.get("elapsed_seconds"),
        }
        text = str(payload["text"] or "").strip()
        if not text:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native executor returned no usable text",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "empty_result",
                    "retryable": True,
                },
            )

        return AIResponse(
            text=text,
            provider="opencode",
            model=canonical_model,
            finish_reason="stop",
        )
