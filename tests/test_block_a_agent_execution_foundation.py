from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.services.agent_environment_provider import AgentEnvironmentAcquireRequest
from app.services.agent_skill_execution_service import (
    build_self_hosted_environment,
    materialize_selected_skills,
    select_minimum_skills,
)
from app.services.harness_improvement_coalition_service import TaskTopologyAssessment
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.openai_agents_contracts import AgentEnvironmentLease
from app.services.openai_agents_runtime_service import (
    MAX_CONCURRENT_OPENAI_SUBAGENTS,
    OpenAIAgentsRuntime,
    build_openai_subagent_plan,
    validate_application_secret_isolation,
)
from app.services.sprite_agent_environment_provider import (
    SpriteAgentEnvironmentProvider,
    SpriteEnvironmentBinding,
)


ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE",str(tmp_path/"block-a.db"))
    initialize_schema()


def _lease(*,expires_delta=600):
    return AgentEnvironmentLease.from_mapping({
        "lease_id":"lease-block-a-1",
        "environment_type":"SPRITE",
        "environment_id":"sprite-provider",
        "approved_domains":["api.openai.com","codex-cloud-environments.chatgpt.com"],
        "approved_apps":["codex-exec-server"],
        "allowed_capabilities":["SANDBOX","openai.agents.session"],
        "time_budget_seconds":600,
        "external_tool_time_budget_seconds":300,
        "max_artifact_bytes":10_000_000,
        "expires_at":(
            datetime.now(timezone.utc)+timedelta(seconds=expires_delta)
        ).isoformat(),
        "task_lease_ref":"delegated-task:task-a",
        "status":"ACTIVE",
    })


def _request(*,lease=None,repo_sha=None):
    return AgentEnvironmentAcquireRequest(
        environment_lease=lease or _lease(),
        mission_id="mission-a",
        goal_id="goal-a",
        task_id="task-a",
        attempt_id="attempt-1",
        openai_session_id="sess-a",
        openai_environment_id="env-openai-a",
        workspace="/workspace/BR",
        repo_sha=repo_sha or "a"*40,
        tree_sha="b"*40,
        mutating=True,
    )


class FakeSpriteBackend:
    def __init__(self):
        self.created=[]
        self.checkpoints=[]
        self.lookups=[]
    def create(self,*,name):
        self.created.append(name)
        return {"id":"sprite-real-id","name":name,"status":"cold"}
    def get(self,*,name):
        self.lookups.append(name)
        return {"id":"sprite-real-id","name":name,"status":"cold"}
    def checkpoint(self,*,name,comment):
        self.checkpoints.append((name,comment))
        return {"checkpoint_id":"checkpoint-a","workspace_digest":"sha256:"+"c"*64}
    def exec(self,*,name,argv,cwd,env=None):
        return {"status":"PASS","name":name,"argv":list(argv),"cwd":cwd}


def _parallel(*,branches=2,shared=False,overlap=False):
    return TaskTopologyAssessment(
        topology="PARALLEL_INDEPENDENT",
        reasons=("BLOCK_A_TEST",),
        evidence={
            "parallelizable_branch_count":branches,
            "shared_mutable_state":shared,
            "write_set_overlap":overlap,
        },
    )


def test_environment_acquire_is_idempotent_one_session_one_active_compute():
    backend=FakeSpriteBackend()
    provider=SpriteAgentEnvironmentProvider(backend=backend)
    first=provider.acquire(_request())
    second=provider.acquire(_request())
    assert first.binding_id==second.binding_id
    assert first.sprite_id==second.sprite_id
    assert len(backend.created)==1


def test_same_session_task_attempt_cannot_rebind_to_different_repo():
    backend=FakeSpriteBackend()
    provider=SpriteAgentEnvironmentProvider(backend=backend)
    provider.acquire(_request())
    with pytest.raises(RuntimeError,match="different active compute binding"):
        provider.acquire(_request(repo_sha="d"*40))
    assert len(backend.created)==1


def test_expired_environment_lease_fails_before_compute_allocation():
    backend=FakeSpriteBackend()
    provider=SpriteAgentEnvironmentProvider(backend=backend)
    with pytest.raises(PermissionError,match="expired"):
        provider.acquire(_request(lease=_lease(expires_delta=-1)))
    assert backend.created==[]


def test_checkpoint_and_reconnect_preserve_same_sprite_identity():
    backend=FakeSpriteBackend()
    provider=SpriteAgentEnvironmentProvider(backend=backend)
    binding=provider.acquire(_request())
    checkpointed=provider.checkpoint(binding.binding_id)
    assert checkpointed.checkpoint_id=="checkpoint-a"
    recovered=provider.reconnect(binding.binding_id)
    assert recovered.binding_id==binding.binding_id
    assert recovered.sprite_id==binding.sprite_id
    assert backend.lookups==[binding.sprite_name]


def test_executor_command_uses_official_self_hosted_shape_without_application_key():
    backend=FakeSpriteBackend()
    binding=SpriteAgentEnvironmentProvider(backend=backend).acquire(_request())
    command=SpriteAgentEnvironmentProvider.executor_command(
        binding,
        remote_url="wss://codex-cloud-environments.chatgpt.com/session/x",
    )
    assert command==(
        "codex","exec-server",
        "--remote","wss://codex-cloud-environments.chatgpt.com/session/x",
        "--environment-id","env-openai-a",
    )
    environment=SpriteAgentEnvironmentProvider.executor_environment()
    assert "OPENAI_API_KEY" not in environment
    assert environment["CODEX_API_KEY"]=="${OPENAI_EXECUTOR_API_KEY}"


def test_binding_rejects_raw_executor_secret_material():
    now=datetime.now(timezone.utc)
    with pytest.raises(PermissionError,match="raw executor credential"):
        SpriteEnvironmentBinding(
            binding_id="binding",
            environment_lease_id="lease",
            mission_id="mission",
            task_id="task",
            attempt_id="attempt",
            openai_session_id="sess",
            openai_environment_id="env",
            sprite_id="sprite",
            sprite_name="sprite-name",
            workspace="/workspace",
            repo_sha="a"*40,
            tree_sha="b"*40,
            checkpoint_id=None,
            status="ACTIVE",
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now+timedelta(minutes=1)).isoformat(),
            executor_credential_ref="sk-proj-raw-secret",
        )


def test_skill_selection_materializes_only_minimum_real_pinned_skill_set(tmp_path):
    selected=select_minimum_skills(
        repo_root=ROOT,
        required_skill_ids=("tdd","handoff"),
        allowed_skill_ids=("tdd","handoff","teach"),
    )
    assert [item.skill_id for item in selected]==["tdd","handoff"]
    plan=materialize_selected_skills(
        repo_root=ROOT,
        capability_root=tmp_path/"capabilities",
        task_id="task-a",
        session_id="sess-a",
        selections={
            "tdd":"maker must follow repository TDD procedure",
            "handoff":"bounded transition artifact required",
        },
        allowed_skill_ids=("tdd","handoff"),
    )
    assert plan.selected_skill_ids==("tdd","handoff")
    assert plan.progressively_loaded is True
    assert len(plan.capability_directories)==1
    parent=Path(plan.capability_directories[0])
    assert {p.name for p in parent.iterdir()}=={"tdd","handoff"}
    assert all(binding.authority=="NONE" for binding in plan.bindings)
    assert all(binding.source_commit for binding in plan.bindings)
    assert all(binding.instruction_hash for binding in plan.bindings)
    environment=build_self_hosted_environment(
        workspace_directory="/workspace/BR",
        skill_plan=plan,
    )
    assert environment["type"]=="self_hosted"
    assert environment["capability_directories"]==[str(parent)]


def test_skill_cannot_expand_task_authority():
    with pytest.raises(PermissionError,match="escapes Harness/Task authorization"):
        select_minimum_skills(
            repo_root=ROOT,
            required_skill_ids=("handoff",),
            allowed_skill_ids=("tdd",),
        )


def test_subagent_ceiling_and_sequential_no_fanout():
    plan=build_openai_subagent_plan(
        topology=_parallel(branches=8),
        requested_subagents=8,
    )
    assert plan.enabled is True
    assert plan.max_concurrent_subagents==MAX_CONCURRENT_OPENAI_SUBAGENTS==3

    sequential=TaskTopologyAssessment(
        topology="SEQUENTIAL",
        reasons=("STRICT_DEPENDENCY",),
        evidence={
            "parallelizable_branch_count":0,
            "shared_mutable_state":False,
            "write_set_overlap":False,
        },
    )
    no_fanout=build_openai_subagent_plan(
        topology=sequential,
        requested_subagents=3,
    )
    assert no_fanout.enabled is False
    assert no_fanout.max_concurrent_subagents==0


def test_write_set_overlap_serializes_parallel_candidate():
    plan=build_openai_subagent_plan(
        topology=_parallel(branches=2,overlap=True),
        requested_subagents=2,
    )
    assert plan.enabled is False
    assert plan.max_concurrent_subagents==0
    assert plan.reason=="TASK_TOPOLOGY_HAS_SHARED_MUTABLE_STATE_OR_WRITE_CONFLICT"


def test_application_secret_isolation_fails_closed():
    clean=validate_application_secret_isolation({
        "session_id":"sess-a",
        "artifact_ref":"sha256:"+"a"*64,
    })
    assert clean["status"]=="PASS"
    assert clean["APPLICATION_OPENAI_API_KEY_IN_AGENT_CONTEXT"]==0
    with pytest.raises(PermissionError,match="secret"):
        validate_application_secret_isolation({
            "OPENAI_API_KEY":"sk-proj-do-not-serialize",
        })


class FakeTransport:
    def __init__(self):
        self.calls=[]
    def __call__(self,*,method,path,body=None,idempotency_key=None):
        self.calls.append({
            "method":method,
            "path":path,
            "body":body,
            "idempotency_key":idempotency_key,
        })
        return {
            "id":"sess-self-hosted-a",
            "status":"in_progress",
            "environment":{
                "id":"env-openai-self-hosted-a",
                "remote_url":"https://api.openai.com/v1/agents/api",
            },
            "latest_turn":{"id":"turn-a","status":"in_progress"},
        }


class CapturingEnvironmentProvider:
    provider_id="sprite"
    def __init__(self):
        self.requests=[]
    def acquire(self,request):
        self.requests.append(request)
        now=datetime.now(timezone.utc)
        return SpriteEnvironmentBinding(
            binding_id="binding-self-hosted-a",
            environment_lease_id=request.environment_lease.lease_id,
            mission_id=request.mission_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            openai_session_id=request.openai_session_id,
            openai_environment_id=request.openai_environment_id,
            sprite_id="sprite-a",
            sprite_name="br-agent-a",
            workspace=request.workspace,
            repo_sha=request.repo_sha,
            tree_sha=request.tree_sha,
            checkpoint_id=None,
            status="ACTIVE",
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=request.environment_lease.expires_at,
            executor_credential_ref="secret-ref:environment-key",
        )


def _execution_auth(execution_id):
    issued=issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:openai.agents.session",
        execution_id=execution_id,
        lineage={
            "source":"block-a-test",
            "capability_id":"openai.agents.session",
        },
    )
    return issued.authorization_id


def test_openai_runtime_binds_self_hosted_compute_through_generic_provider_only():
    transport=FakeTransport()
    provider=CapturingEnvironmentProvider()
    runtime=OpenAIAgentsRuntime(
        transport=transport,
        environment_provider=provider,
    )
    receipt=runtime.create_session(
        authorization_ref=_execution_auth("block-a:self-hosted:1"),
        execution_id="block-a:self-hosted:1",
        agent_config={
            "model":"gpt-6.1-sol",
            "reasoning":{"effort":"low"},
            "multi_agent":{"enabled":False},
        },
        environment={
            "type":"self_hosted",
            "workspace_directory":"/workspace/BR",
            "capability_directories":[],
        },
        initial_input="bounded provider-neutral task",
        trace_refs=("mission:mission-a","task:task-a"),
        task_id="task-a",
        attempt_id="attempt-1",
        environment_lease=_lease(),
        environment_context={
            "mission_id":"mission-a",
            "goal_id":"goal-a",
            "workspace":"/workspace/BR",
            "repo_sha":"a"*40,
            "tree_sha":"b"*40,
            "mutating":True,
        },
    )
    assert receipt.session_id=="sess-self-hosted-a"
    assert receipt.environment_id=="env-openai-self-hosted-a"
    assert "sprite-binding:binding-self-hosted-a" in receipt.trace_refs
    assert len(provider.requests)==1
    request=provider.requests[0]
    assert request.openai_session_id==receipt.session_id
    assert request.openai_environment_id==receipt.environment_id
    assert "OPENAI_API_KEY" not in str(request.to_dict())
    assert transport.calls[0]["body"]["environment"]["type"]=="self_hosted"


def test_self_hosted_session_fails_closed_without_environment_provider():
    transport=FakeTransport()
    runtime=OpenAIAgentsRuntime(transport=transport)
    with pytest.raises(PermissionError,match="AgentEnvironmentProvider"):
        runtime.create_session(
            authorization_ref=_execution_auth("block-a:self-hosted:no-provider"),
            execution_id="block-a:self-hosted:no-provider",
            agent_config={
                "model":"gpt-6.1-sol",
                "reasoning":{"effort":"low"},
                "multi_agent":{"enabled":False},
            },
            environment={
                "type":"self_hosted",
                "workspace_directory":"/workspace/BR",
                "capability_directories":[],
            },
            initial_input="x",
            trace_refs=(),
            task_id="task-a",
            attempt_id="attempt-1",
            environment_lease=_lease(),
            environment_context={
                "mission_id":"mission-a",
                "goal_id":"goal-a",
                "workspace":"/workspace/BR",
                "repo_sha":"a"*40,
                "tree_sha":"b"*40,
            },
        )
    assert transport.calls==[]
