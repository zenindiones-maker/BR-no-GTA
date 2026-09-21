from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from app.database import harness_learning_repository as repository
from app.services.agent_office.codex_auth import CodexAuthenticationProvider
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.memory_plane_service import evaluate_memory_candidate


AUTH_AVAILABLE = "AVAILABLE"
AUTH_USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
AUTH_BLOCKED = "BLOCKED"
AUTH_EXPIRED = "EXPIRED"
AUTH_UNAVAILABLE = "UNAVAILABLE"

AUTH_FAILURE_PATTERN = "codex_device_auth_wait_timeout"
INCIDENT_RUN_ID = "35633234932"
INCIDENT_EVIDENCE = f"github:run:{INCIDENT_RUN_ID}:codex-device-auth-wait-timeout"


@dataclass(frozen=True)
class CodexAuthLease:
    lease_id: str
    mission_id: str
    auth_method: str
    availability: str
    observed_at: str
    expires_at: str | None
    evidence_refs: tuple[str, ...]
    credential_material_persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodexAuthPreflight:
    state: str
    auth_available: bool
    method: str
    cost_class: str
    user_action_required: bool
    paired_human_available: bool
    delivery_surface: str
    failure_memory_retrieved: bool
    failure_memory_id: str | None
    auth_timeout_path_repeated: bool
    lease: CodexAuthLease | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["lease"] = self.lease.to_dict() if self.lease else None
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _active_auth_failure_memory() -> dict[str, Any] | None:
    rows = repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="development-auth",
        task_class="codex-auth-preflight",
        failure_pattern=AUTH_FAILURE_PATTERN,
        limit=20,
    )
    return rows[0] if rows else None


def ensure_real_auth_failure_memory() -> dict[str, Any]:
    existing = _active_auth_failure_memory()
    if existing is not None:
        return existing

    now = _now()
    episode_id = "episode-codex-auth-timeout-35633234932"
    episode = HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-natural-system-improvement-live",
        decision_id="decision-codex-auth-timeout-35633234932",
        execution_id="execution-codex-auth-timeout-35633234932",
        task_id="codex-auth-prerequisite",
        agent_id="auth-control-plane",
        capability_id="agent-office.codex-auth",
        domain="development-auth",
        task_class="codex-auth-preflight",
        started_at=now,
        finished_at=now,
        duration_seconds=900.0,
        status="BLOCKED",
        actual_outcome={
            "observed": True,
            "source_run_id": INCIDENT_RUN_ID,
            "user_action_required": True,
            "runner_waited_for_human": True,
            "delivery_surface": "REVIEW_CHANNEL_OR_GROUP",
        },
        outcome_evidence=(INCIDENT_EVIDENCE,),
        evidence_refs=(INCIDENT_EVIDENCE,),
        error=(
            "codex_device_auth_wait_timeout: device auth required; delivery surface "
            "was review group; ephemeral runner held waiting for human approval"
        ),
        retry_count=0,
        human_intervention=True,
        qa_results={"auth_prerequisite": "BLOCKED"},
        run_ref=f"github:run:{INCIDENT_RUN_ID}",
        lineage={
            "classification": "AUTH_PREREQUISITE_BLOCKED",
            "agent_competence_penalty": False,
            "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
        },
    )
    persist_episode(episode)
    candidates = [
        item
        for item in repository.list_memories(status="CANDIDATE", limit=200)
        if episode_id in (item.get("source_episode_ids") or ())
    ]
    if not candidates:
        raise RuntimeError("real Codex auth incident did not create a FailureMemory candidate")
    candidate = candidates[0]
    auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{candidate['memory_id']}",
        harness_decision_id="decision-promote-codex-auth-timeout",
        execution_id="execution-promote-codex-auth-timeout",
        lineage={
            "source_run_id": INCIDENT_RUN_ID,
            "failure_pattern": AUTH_FAILURE_PATTERN,
        },
    )
    evaluated = evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="PROMOTE",
        reason=(
            "Observed run 35633234932 wasted an ephemeral runner waiting for Codex "
            "device authorization; future development missions must preflight auth and "
            "create a persistent human gate instead of repeating the wait path."
        ),
        evidence_refs=(INCIDENT_EVIDENCE,),
        authorization=auth,
    )
    return dict(evaluated["memory"])


def _lease(*, mission_id: str, method: str, evidence_refs: tuple[str, ...]) -> CodexAuthLease:
    observed = _now()
    return CodexAuthLease(
        lease_id=_stable_id("codex-auth-lease", {
            "mission_id": mission_id,
            "method": method,
            "observed_at": observed,
        }),
        mission_id=mission_id,
        auth_method=method,
        availability=AUTH_AVAILABLE,
        observed_at=observed,
        expires_at=None,
        evidence_refs=evidence_refs,
        credential_material_persisted=False,
    )


def classify_codex_auth(
    *,
    mission_id: str,
    cwd: Path,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., CodexAuthenticationProvider] = CodexAuthenticationProvider,
) -> CodexAuthPreflight:
    source = dict(os.environ if environ is None else environ)
    failure = ensure_real_auth_failure_memory()
    paired = bool(source.get("TELEGRAM_ALLOWED_USER_ID", "").strip())

    provider = provider_factory(environ=source)
    state = provider.bootstrap(cwd=cwd, timeout=30, allow_device_auth=False)

    if state.available:
        lease = _lease(
            mission_id=mission_id,
            method=state.method,
            evidence_refs=(
                f"codex-auth-status:{state.method}",
                f"failure-memory:{failure['memory_id']}",
            ),
        )
        return CodexAuthPreflight(
            state=AUTH_AVAILABLE,
            auth_available=True,
            method=state.method,
            cost_class=state.cost_class,
            user_action_required=False,
            paired_human_available=paired,
            delivery_surface="NONE",
            failure_memory_retrieved=True,
            failure_memory_id=str(failure["memory_id"]),
            auth_timeout_path_repeated=False,
            lease=lease,
            reason="trusted noninteractive or cached Codex authentication is available",
        )

    federation_rule = source.get("OPENAI_FEDERATION_RULE_ID", "").strip()
    identity_file = source.get("OPENAI_IDENTITY_TOKEN_FILE", "").strip()
    if bool(federation_rule) != bool(identity_file):
        auth_state = AUTH_BLOCKED
        reason = "workload identity configuration is incomplete"
    elif state.cost_class == "paid_api":
        auth_state = AUTH_BLOCKED
        reason = "paid API authentication is not eligible under ZERO_COST_OPERATION"
    elif paired:
        auth_state = AUTH_USER_ACTION_REQUIRED
        reason = (
            "no trusted resumable noninteractive Codex authentication is available; "
            "mission must checkpoint before any heavy development bootstrap"
        )
    else:
        auth_state = AUTH_UNAVAILABLE
        reason = (
            "no trusted Codex authentication and no paired Telegram human destination"
        )

    return CodexAuthPreflight(
        state=auth_state,
        auth_available=False,
        method=state.method,
        cost_class=state.cost_class,
        user_action_required=(auth_state == AUTH_USER_ACTION_REQUIRED),
        paired_human_available=paired,
        delivery_surface="PAIRED_USER_DM" if paired else "NONE",
        failure_memory_retrieved=True,
        failure_memory_id=str(failure["memory_id"]),
        auth_timeout_path_repeated=False,
        lease=None,
        reason=reason,
    )


def build_mission_checkpoint(
    *,
    dispatch_id: str,
    mission_id: str,
    target_ref: str,
    target_sha: str,
    plan_b64: str,
    human_goal_b64: str,
    telegram_chat_id: str,
    preflight: CodexAuthPreflight,
) -> dict[str, Any]:
    checkpoint = {
        "schema": "dynamic-system-improvement-auth-checkpoint/v1",
        "dispatch_id": dispatch_id,
        "mission_id": mission_id,
        "target_ref": target_ref,
        "target_sha": target_sha,
        "plan_b64": plan_b64,
        "human_goal_b64": human_goal_b64,
        "telegram_chat_id": telegram_chat_id,
        "auth_state": preflight.state,
        "auth_method": preflight.method,
        "failure_memory_id": preflight.failure_memory_id,
        "created_at": _now(),
        "authority": "DEEPSEEK_HARNESS",
        "credential_material_persisted": False,
        "agent_direct_promotion": False,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    checkpoint["checkpoint_id"] = _stable_id(
        "auth-checkpoint",
        {
            "dispatch_id": dispatch_id,
            "mission_id": mission_id,
            "target_sha": target_sha,
        },
    )
    return checkpoint


def write_checkpoint(path: Path, checkpoint: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(checkpoint), ensure_ascii=False, indent=2, sort_keys=True)
    lowered = text.lower()
    for forbidden in ("access_token", "refresh_token", "api_key", "user_code", "credential":"):
        if forbidden in lowered:
            raise PermissionError("auth checkpoint contains forbidden credential material")
    path.write_text(text + "\n", encoding="utf-8")


def load_checkpoint(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "dynamic-system-improvement-auth-checkpoint/v1":
        raise ValueError("unsupported auth checkpoint schema")
    if data.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("auth checkpoint escaped Harness authority")
    if data.get("credential_material_persisted") is not False:
        raise PermissionError("auth checkpoint persisted credential material")
    return data



def resolve_checkpoint_after_auth(
    *,
    checkpoint_path: Path,
    cwd: Path,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., CodexAuthenticationProvider] = CodexAuthenticationProvider,
) -> dict[str, Any]:
    checkpoint = load_checkpoint(checkpoint_path)
    mission_id = str(checkpoint["mission_id"])
    preflight = classify_codex_auth(
        mission_id=mission_id,
        cwd=cwd,
        environ=environ,
        provider_factory=provider_factory,
    )
    if not preflight.auth_available or preflight.lease is None:
        return {
            "status": "AUTHORIZATION_PENDING_HUMAN",
            "mission_id": mission_id,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "auth_state": preflight.state,
            "AUTH_GATE_RESOLVED": "NO",
            "MISSION_RESUMED_FROM_CHECKPOINT": "NO",
            "credential_material_persisted": False,
        }
    return {
        "status": "RESUME_READY",
        "mission_id": mission_id,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "target_ref": checkpoint["target_ref"],
        "target_sha": checkpoint["target_sha"],
        "plan_b64": checkpoint["plan_b64"],
        "human_goal_b64": checkpoint["human_goal_b64"],
        "telegram_chat_id": checkpoint["telegram_chat_id"],
        "auth_state": preflight.state,
        "auth_lease": preflight.lease.to_dict(),
        "AUTH_GATE_RESOLVED": "PASS",
        "MISSION_RESUMED_FROM_CHECKPOINT": "PASS",
        "credential_material_persisted": False,
    }
