from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Protocol

from app.services.agent_environment_provider import (
    AgentEnvironmentAcquireRequest,
    assert_environment_binding_fresh,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:24]}"


@dataclass(frozen=True)
class SpriteEnvironmentBinding:
    binding_id: str
    environment_lease_id: str
    mission_id: str
    task_id: str
    attempt_id: str
    openai_session_id: str
    openai_environment_id: str
    sprite_id: str
    sprite_name: str
    workspace: str
    repo_sha: str
    tree_sha: str
    checkpoint_id: str | None
    status: str
    created_at: str
    updated_at: str
    expires_at: str
    workspace_digest: str | None = None
    executor_credential_ref: str | None = None
    schema: str = "SpriteEnvironmentBinding/v1"

    def __post_init__(self) -> None:
        status = str(self.status or "").upper()
        if status not in {"ACTIVE", "COLD", "RECONNECTING", "RELEASED", "EXPIRED", "FAILED"}:
            raise ValueError("invalid Sprite environment binding status")
        if not str(self.binding_id).strip():
            raise ValueError("binding_id is required")
        if not str(self.openai_session_id).strip():
            raise ValueError("openai_session_id is required")
        if not str(self.sprite_id).strip() or not str(self.sprite_name).strip():
            raise ValueError("Sprite identity is required")
        if not str(self.workspace).startswith("/"):
            raise ValueError("workspace must be absolute")
        if len(str(self.repo_sha)) != 40 or len(str(self.tree_sha)) != 40:
            raise ValueError("repo/tree SHA must be full git SHAs")
        if self.executor_credential_ref and (
            "sk-" in self.executor_credential_ref or "Bearer " in self.executor_credential_ref
        ):
            raise PermissionError("raw executor credential must not be persisted")

    def assert_active(self) -> None:
        assert_environment_binding_fresh(
            expires_at=self.expires_at,
            status=self.status,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpriteEnvironmentBackend(Protocol):
    def create(self, *, name: str) -> Mapping[str, Any]:
        ...

    def get(self, *, name: str) -> Mapping[str, Any]:
        ...

    def checkpoint(self, *, name: str, comment: str) -> Mapping[str, Any]:
        ...

    def exec(
        self,
        *,
        name: str,
        argv: tuple[str, ...],
        cwd: str,
        env: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        ...


class SpriteAgentEnvironmentProvider:
    provider_id = "sprite"

    def __init__(self, *, backend: SpriteEnvironmentBackend) -> None:
        self.backend = backend

    @staticmethod
    def _workload_name(request: AgentEnvironmentAcquireRequest) -> str:
        digest = sha256(
            (
                request.mission_id
                + "\n"
                + request.task_id
                + "\n"
                + request.attempt_id
                + "\n"
                + request.openai_session_id
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"br-agent-{digest}"

    def acquire(self, request: AgentEnvironmentAcquireRequest) -> SpriteEnvironmentBinding:
        from app.database.openai_agents_repository import (
            get_active_sprite_environment_binding,
            persist_sprite_environment_binding,
        )

        existing = get_active_sprite_environment_binding(
            openai_session_id=request.openai_session_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
        )
        if existing is not None:
            if (
                existing["environment_lease_id"] != request.environment_lease.lease_id
                or existing["repo_sha"] != request.repo_sha
                or existing["tree_sha"] != request.tree_sha
            ):
                raise RuntimeError(
                    "same OpenAI session/task/attempt already has a different active compute binding"
                )
            return SpriteEnvironmentBinding(**{
                key: existing.get(key)
                for key in SpriteEnvironmentBinding.__dataclass_fields__
                if key in existing
            })

        workload_name = self._workload_name(request)
        remote = dict(self.backend.create(name=workload_name))
        sprite_id = str(remote.get("id") or "").strip()
        sprite_name = str(remote.get("name") or workload_name).strip()
        if not sprite_id or not sprite_name:
            raise RuntimeError("Sprite backend did not return durable identity")

        created = _now()
        binding = SpriteEnvironmentBinding(
            binding_id=_stable_id(
                "sprite-binding",
                {
                    "lease": request.environment_lease.lease_id,
                    "session": request.openai_session_id,
                    "task": request.task_id,
                    "attempt": request.attempt_id,
                    "sprite": sprite_id,
                },
            ),
            environment_lease_id=request.environment_lease.lease_id,
            mission_id=request.mission_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            openai_session_id=request.openai_session_id,
            openai_environment_id=request.openai_environment_id,
            sprite_id=sprite_id,
            sprite_name=sprite_name,
            workspace=request.workspace,
            repo_sha=request.repo_sha,
            tree_sha=request.tree_sha,
            checkpoint_id=None,
            status="ACTIVE",
            created_at=created,
            updated_at=created,
            expires_at=request.environment_lease.expires_at,
            workspace_digest=None,
            executor_credential_ref="secret-ref:openai-executor-environment-key",
        )
        persisted = persist_sprite_environment_binding(binding)
        return SpriteEnvironmentBinding(**{
            key: persisted.get(key)
            for key in SpriteEnvironmentBinding.__dataclass_fields__
            if key in persisted
        })

    def reconnect(self, binding_id: str) -> SpriteEnvironmentBinding:
        from app.database.openai_agents_repository import (
            get_sprite_environment_binding,
            persist_sprite_environment_binding,
        )

        current = get_sprite_environment_binding(binding_id)
        if current is None:
            raise LookupError("Sprite environment binding not found")
        binding = SpriteEnvironmentBinding(**{
            key: current.get(key)
            for key in SpriteEnvironmentBinding.__dataclass_fields__
            if key in current
        })
        binding.assert_active()
        remote = dict(self.backend.get(name=binding.sprite_name))
        observed_id = str(remote.get("id") or "")
        if observed_id and observed_id != binding.sprite_id:
            raise RuntimeError("Sprite identity drift during reconnect")
        updated = replace(binding, status="ACTIVE", updated_at=_now())
        persist_sprite_environment_binding(updated)
        return updated

    def checkpoint(self, binding_id: str) -> SpriteEnvironmentBinding:
        from app.database.openai_agents_repository import (
            get_sprite_environment_binding,
            persist_sprite_environment_binding,
        )

        current = get_sprite_environment_binding(binding_id)
        if current is None:
            raise LookupError("Sprite environment binding not found")
        binding = SpriteEnvironmentBinding(**{
            key: current.get(key)
            for key in SpriteEnvironmentBinding.__dataclass_fields__
            if key in current
        })
        binding.assert_active()
        result = dict(
            self.backend.checkpoint(
                name=binding.sprite_name,
                comment=(
                    f"BR Block A {binding.mission_id}/{binding.task_id}/"
                    f"{binding.attempt_id} repo={binding.repo_sha}"
                ),
            )
        )
        checkpoint_id = str(
            result.get("checkpoint_id")
            or result.get("id")
            or result.get("checkpoint", {}).get("id")
            or ""
        ).strip()
        if not checkpoint_id:
            raise RuntimeError("Sprite checkpoint did not return checkpoint identity")
        workspace_digest = str(
            result.get("workspace_digest")
            or result.get("digest")
            or ""
        ).strip() or None
        updated = replace(
            binding,
            checkpoint_id=checkpoint_id,
            workspace_digest=workspace_digest,
            updated_at=_now(),
        )
        persist_sprite_environment_binding(updated)
        return updated

    def release(self, binding_id: str) -> SpriteEnvironmentBinding:
        from app.database.openai_agents_repository import (
            get_sprite_environment_binding,
            persist_sprite_environment_binding,
        )

        current = get_sprite_environment_binding(binding_id)
        if current is None:
            raise LookupError("Sprite environment binding not found")
        binding = SpriteEnvironmentBinding(**{
            key: current.get(key)
            for key in SpriteEnvironmentBinding.__dataclass_fields__
            if key in current
        })
        updated = replace(binding, status="RELEASED", updated_at=_now())
        persist_sprite_environment_binding(updated)
        return updated

    @staticmethod
    def executor_command(
        binding: SpriteEnvironmentBinding,
        *,
        remote_url: str,
    ) -> tuple[str, ...]:
        binding.assert_active()
        remote = str(remote_url or "").strip()
        if not remote.startswith("wss://") and not remote.startswith("https://"):
            raise ValueError("OpenAI self-hosted remote_url must be HTTPS/WSS")
        return (
            "codex",
            "exec-server",
            "--remote",
            remote,
            "--environment-id",
            binding.openai_environment_id,
        )

    @staticmethod
    def executor_environment() -> dict[str, str]:
        return {
            "CODEX_API_KEY": "$" + "{OPENAI_EXECUTOR_API_KEY}",
        }


__all__ = [
    "SpriteAgentEnvironmentProvider",
    "SpriteEnvironmentBackend",
    "SpriteEnvironmentBinding",
]
