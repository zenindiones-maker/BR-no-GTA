from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.services.agent_office.delegation import DelegatedTaskLease
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_improvement_coalition_service import TaskTopologyAssessment
from app.services.openai_agents_contracts import (
    AgentEnvironmentLease,
    ModelEligibility,
    OpenAIAgentSessionReceipt,
    OpenAIModelCapability,
    OpenAISubagentPlan,
    SelectedSkillSpec,
    classify_openai_session_state,
)
from app.services.openai_agents_http_client import OpenAIAgentsAPIError


MAX_CONCURRENT_OPENAI_SUBAGENTS=3
_PARALLEL_TOPOLOGIES=frozenset({"PARALLEL_INDEPENDENT","PARALLEL_WITH_REDUCTION"})


def _now()->str:
    return datetime.now(timezone.utc).isoformat()



def gpt_6_1_sol_profile()->OpenAIModelCapability:
    return OpenAIModelCapability(
        model_id="gpt-6.1-sol",
        provider_id="openai",
        context_window_tokens=1_050_000,
        max_output_tokens=128_000,
        reasoning_efforts=("low","medium","high","xhigh","max"),
        tool_support=(
            "functions","web_search","file_search","image_generation",
            "code_interpreter","hosted_shell","apply_patch","skills",
            "computer_use","mcp","tool_search",
        ),
        routing_status="INELIGIBLE_WITH_REASON",
        live_proof_status="NOT_PROVEN",
        availability_state="AVAILABLE_IN_API_DOCUMENTATION",
        source_refs=(
            "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
            "https://developers.openai.com/api/docs/guides/agents-api",
        ),
    )



def require_registered_openai_model(
    model_id:str,
    *,
    registry:Any|None=None,
)->Any:
    """Fail closed unless Harness Registry contains the selected OpenAI model."""
    model=str(model_id or "").strip()
    if not model:
        raise PermissionError("OpenAI Agents model is required")
    if registry is None:
        from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
        registry=GLOBAL_CAPABILITY_REGISTRY
    matches=tuple(
        record for record in registry.all()
        if str(getattr(record,"capability_type",""))=="PROVIDER"
        and str(getattr(record,"provider_id",""))=="openai"
        and str(getattr(record,"model_id",""))==model
    )
    if len(matches)!=1:
        raise PermissionError("OpenAI Agents model is not registered exactly once")
    return matches[0]


def classify_model_eligibility(
    *,
    model_id:str,
    credentials_present:bool,
    runtime_probe:Mapping[str,Any]|None,
)->ModelEligibility:
    model=str(model_id or "")
    if model != "gpt-6.1-sol":
        return ModelEligibility(model,"INELIGIBLE_WITH_REASON","MODEL_NOT_REGISTERED")
    if not credentials_present:
        return ModelEligibility(model,"INELIGIBLE_WITH_REASON","OPENAI_CREDENTIAL_UNAVAILABLE")
    if runtime_probe is None:
        return ModelEligibility(model,"INELIGIBLE_WITH_REASON","LIVE_MODEL_ACCESS_UNPROVEN")
    state=str(runtime_probe.get("status") or "").upper()
    observed=str(runtime_probe.get("model_id") or "")
    refs=tuple(str(x) for x in (runtime_probe.get("evidence_refs") or ()) if str(x))
    if state in {"PASS","SUCCESS","AVAILABLE"} and observed==model:
        return ModelEligibility(model,"FUNCTIONAL","LIVE_MODEL_ACCESS_PROVEN",refs)
    return ModelEligibility(
        model,"INELIGIBLE_WITH_REASON",
        str(runtime_probe.get("reason") or state or "LIVE_MODEL_ACCESS_FAILED"),
        refs,
    )


def build_openai_subagent_plan(
    *,
    topology:TaskTopologyAssessment,
    requested_subagents:int,
)->OpenAISubagentPlan:
    kind=str(topology.topology or "").upper()
    evidence=dict(topology.evidence or {})
    if kind not in _PARALLEL_TOPOLOGIES:
        return OpenAISubagentPlan(
            enabled=False,
            max_concurrent_subagents=0,
            topology=kind,
            reason="TASK_TOPOLOGY_DOES_NOT_JUSTIFY_OPENAI_SUBAGENTS",
        )
    if bool(evidence.get("shared_mutable_state")) or bool(evidence.get("write_set_overlap")):
        return OpenAISubagentPlan(
            enabled=False,
            max_concurrent_subagents=0,
            topology=kind,
            reason="TASK_TOPOLOGY_HAS_SHARED_MUTABLE_STATE_OR_WRITE_CONFLICT",
        )
    branches=max(0,int(evidence.get("parallelizable_branch_count") or 0))
    ceiling=min(
        max(0,int(requested_subagents)),
        branches if branches>0 else MAX_CONCURRENT_OPENAI_SUBAGENTS,
        MAX_CONCURRENT_OPENAI_SUBAGENTS,
    )
    return OpenAISubagentPlan(
        enabled=ceiling>0,
        max_concurrent_subagents=ceiling,
        topology=kind,
        reason="INDEPENDENT_PARALLEL_WORK_BOUNDED",
    )


def build_tool_search_configuration(
    *,
    namespaces:Sequence[str],
    selected_namespaces:Sequence[str],
)->dict[str,Any]:
    available=tuple(dict.fromkeys(str(x) for x in namespaces))
    selected=tuple(dict.fromkeys(str(x) for x in selected_namespaces))
    if not set(selected).issubset(set(available)):
        raise PermissionError("tool search namespace escapes available namespace set")
    return {
        "type":"tool_search",
        "defer_loading":True,
        "allowed_namespaces":list(selected),
    }


def build_openai_agent_configuration(
    *,
    model_profile:OpenAIModelCapability,
    reasoning_effort:str,
    selected_skills:Sequence[SelectedSkillSpec],
    tool_search:Mapping[str,Any]|None,
    multi_agent_plan:OpenAISubagentPlan,
)->dict[str,Any]:
    effort=str(reasoning_effort)
    if effort not in model_profile.reasoning_efforts:
        raise ValueError("reasoning effort is not supported by selected model")
    skills=[]
    for skill in selected_skills:
        if not skill.eligible or skill.grants_authority:
            continue
        skills.append({
            "skill_id":skill.skill_id,
            "version":skill.version,
            "source":skill.source,
            "instruction_hash":skill.instruction_hash,
            "directory":skill.directory,
            "grants_authority":False,
        })
    result={
        "model":model_profile.model_id,
        "reasoning":{"effort":effort},
        "multi_agent":{
            "enabled":multi_agent_plan.enabled,
            "max_concurrent_subagents":multi_agent_plan.max_concurrent_subagents,
        },
        "skills":skills,
    }
    if tool_search is not None:
        result["tool_search"]=dict(tool_search)
    return result


def authorize_openai_execution_scope(
    *,
    task_envelope:Any,
    task_lease:DelegatedTaskLease,
    responsibility:Any,
    custom_rules:Sequence[Any],
    requested_tools:Sequence[str],
    requested_skills:Sequence[str],
    risk_class:str,
    environment_lease:AgentEnvironmentLease|None=None,
    skill_allowed_tools:Sequence[str]|None=None,
    tool_policy_allowed_tools:Sequence[str]|None=None,
)->dict[str,Any]:
    """Compute effective OpenAI runtime authority strictly by intersection."""
    task_lease.assert_active()
    if str(task_envelope.task_id)!=str(task_lease.task_id):
        raise PermissionError("TaskEnvelope and DelegatedTaskLease task mismatch")
    if str(task_envelope.mission_id)!=str(task_lease.mission_id):
        raise PermissionError("TaskEnvelope and DelegatedTaskLease mission mismatch")
    if str(task_envelope.goal_id)!=str(task_lease.goal_id):
        raise PermissionError("TaskEnvelope and DelegatedTaskLease goal mismatch")
    if str(task_envelope.action).upper() not in {str(x).upper() for x in task_lease.allowed_actions}:
        raise PermissionError("DelegatedTaskLease does not authorize TaskEnvelope action")
    if str(task_envelope.capability_id) not in set(task_lease.capability_ids):
        raise PermissionError("DelegatedTaskLease does not authorize TaskEnvelope capability")
    if not bool(responsibility.enabled):
        raise PermissionError("PersistentResponsibility is disabled")
    if str(task_envelope.task_class) not in set(responsibility.task_classes):
        raise PermissionError("PersistentResponsibility does not authorize task class")

    task_tools=set(str(x) for x in task_envelope.allowed_tools)
    lease_tools=set(str(x) for x in task_lease.allowed_tools)
    responsibility_tools=set(str(x) for x in responsibility.allowed_tools)
    effective_tools=task_tools & lease_tools & responsibility_tools

    if environment_lease is not None:
        environment_lease.assert_active()
        if environment_lease.task_lease_ref!=f"delegated-task:{task_lease.task_id}":
            raise PermissionError("AgentEnvironmentLease does not bind selected Task lease")
        environment_tools=set(str(x) for x in environment_lease.allowed_capabilities)
        # An environment never adds permission. When explicit capability/tool names
        # are supplied, it can only narrow the already-authorized tool set.
        if environment_tools:
            effective_tools={
                tool for tool in effective_tools
                if tool in environment_tools
                or tool.upper() in environment_tools
                or "SANDBOX" in environment_tools
            }

    if skill_allowed_tools is not None:
        effective_tools &= set(str(x) for x in skill_allowed_tools)
    if tool_policy_allowed_tools is not None:
        effective_tools &= set(str(x) for x in tool_policy_allowed_tools)

    requested_tool_set=set(str(x) for x in requested_tools)
    if not requested_tool_set.issubset(effective_tools):
        raise PermissionError("requested tool escapes authorization intersection")

    responsibility_skills=set(str(x) for x in responsibility.allowed_skills)
    requested_skill_set=set(str(x) for x in requested_skills)
    if not requested_skill_set.issubset(responsibility_skills):
        raise PermissionError("requested skill escapes PersistentResponsibility")

    matched_rule_ids=[]
    if custom_rules:
        from app.services.persistent_intelligence_force_service import evaluate_custom_rule
        for tool in sorted(requested_tool_set):
            decision=evaluate_custom_rule(
                custom_rules,
                responsibility_id=responsibility.responsibility_id,
                action="TOOL_USE",
                target=tool,
                risk_class=str(risk_class or "READ_ONLY").upper(),
            )
            if decision.effect not in {"ALLOW","PREAPPROVE_IF_EXPLICITLY_REQUESTED"}:
                raise PermissionError("AgentCustomRule does not authorize requested tool")
            matched_rule_ids.extend(decision.matched_rule_ids)

    return {
        "schema":"OpenAIExecutionAuthorizationDecision/v1",
        "allowed":True,
        "task_id":task_envelope.task_id,
        "mission_id":task_envelope.mission_id,
        "responsibility_id":responsibility.responsibility_id,
        "allowed_tools":sorted(requested_tool_set),
        "allowed_skills":sorted(requested_skill_set),
        "matched_rule_ids":sorted(set(matched_rule_ids)),
        "environment_lease_id":(
            environment_lease.lease_id if environment_lease is not None else None
        ),
        "authorization_semantics":"INTERSECTION_ONLY",
        "grants_authority":False,
    }


def verify_openai_task_completion(
    receipt:OpenAIAgentSessionReceipt,
    *,
    task_envelope:Any,
    task_result:Any,
    verification_ref:str,
)->OpenAIAgentSessionReceipt:
    """Harness-side reduction gate from runtime evidence to BR task completion."""
    from app.services.task_result_envelope_service import TASK_RESULT_ENVELOPE_SCHEMA

    if receipt.state!="TURN_COMPLETED":
        raise PermissionError("only TURN_COMPLETED may enter Harness verification")
    if str(task_result.schema)!=TASK_RESULT_ENVELOPE_SCHEMA:
        raise PermissionError("TaskResultEnvelope schema mismatch")
    if str(task_result.task_id)!=str(task_envelope.task_id):
        raise PermissionError("TaskResultEnvelope task mismatch")
    if str(task_result.mission_id)!=str(task_envelope.mission_id):
        raise PermissionError("TaskResultEnvelope mission mismatch")
    if str(task_result.capability_id)!=str(task_envelope.capability_id):
        raise PermissionError("TaskResultEnvelope capability mismatch")
    if str(task_result.status).upper() not in {"COMPLETED","SUCCESS"}:
        raise PermissionError("TaskResultEnvelope is not completed")
    required=set(str(x) for x in (task_envelope.expected_outputs or ()) if str(x))
    produced=set(str(x) for x in (task_result.output_artifact_refs or ()) if str(x))
    if not required.issubset(produced):
        raise PermissionError("required output artifact is missing")
    return _mark_openai_task_verified(receipt,verification_ref=verification_ref)


def validate_application_secret_isolation(value:Any)->dict[str,Any]:
    """Fail closed if application OpenAI credentials enter agent-visible state."""
    import json
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,default=str)
    lowered=raw.lower()
    forbidden=(
        "openai_api_key",
        "authorization: bearer",
        '"authorization":"bearer',
        "sk-proj-",
        '"api_key"',
        '"access_token"',
        '"refresh_token"',
    )
    matched=tuple(item for item in forbidden if item in lowered)
    if matched:
        raise PermissionError("application OpenAI secret entered agent-visible state")
    return {
        "schema":"ApplicationSecretIsolationDecision/v1",
        "APPLICATION_OPENAI_API_KEY_IN_AGENT_CONTEXT":0,
        "APPLICATION_OPENAI_API_KEY_IN_ARTIFACTS":0,
        "matched_secret_patterns":[],
        "status":"PASS",
    }


def require_bounded_computer_use(
    *,
    environment_lease:AgentEnvironmentLease,
    task_lease:DelegatedTaskLease,
    requested_domain:str,
    requested_app:str,
    requested_seconds:int,
)->dict[str,Any]:
    environment_lease.assert_active()
    task_lease.assert_active()
    if environment_lease.task_lease_ref!=f"delegated-task:{task_lease.task_id}":
        raise PermissionError("computer use environment lease task binding mismatch")
    if (
        "openai.computer-use" not in task_lease.capability_ids
        and "openai.computer-use" not in task_lease.allowed_tools
    ):
        raise PermissionError("DelegatedTaskLease does not permit computer use")
    if "COMPUTER_USE" not in environment_lease.allowed_capabilities:
        raise PermissionError("environment lease does not permit computer use")
    domain=str(requested_domain or "").lower().strip()
    app=str(requested_app or "").strip()
    if domain not in {x.lower() for x in environment_lease.approved_domains}:
        raise PermissionError("computer use domain is not allowlisted")
    if app not in set(environment_lease.approved_apps):
        raise PermissionError("computer use app is not allowlisted")
    seconds=int(requested_seconds)
    if seconds<=0 or seconds>environment_lease.external_tool_time_budget_seconds:
        raise PermissionError("computer use time exceeds environment budget")
    return {
        "schema":"OpenAIComputerUseDecision/v1",
        "allowed":True,
        "environment_id":environment_lease.environment_id,
        "task_id":task_lease.task_id,
        "domain":domain,
        "app":app,
        "requested_seconds":seconds,
        "screenshot_evidence_required":True,
        "activity_evidence_required":True,
        "result_verification_required":True,
        "grants_authority":False,
    }


def _mark_openai_task_verified(
    receipt:OpenAIAgentSessionReceipt,
    *,
    verification_ref:str,
)->OpenAIAgentSessionReceipt:
    if receipt.state!="TURN_COMPLETED":
        raise PermissionError("only TURN_COMPLETED may be Harness-verified")
    ref=str(verification_ref or "").strip()
    if not ref:
        raise ValueError("verification_ref is required")
    return replace(
        receipt,
        state="TASK_VERIFIED",
        trace_refs=tuple(dict.fromkeys((*receipt.trace_refs,ref))),
        updated_at=_now(),
        revision=receipt.revision+1,
    )


def _turn_from_session(session:Mapping[str,Any],prior_turn_id:str|None=None)->dict[str,Any]:
    for key in ("current_turn","latest_turn","last_turn"):
        raw=session.get(key)
        if isinstance(raw,Mapping):
            return dict(raw)
    required=session.get("required_actions") or ()
    turn_id=next(
        (str(x.get("turn_id")) for x in required if isinstance(x,Mapping) and x.get("turn_id")),
        prior_turn_id or "",
    )
    return {
        "id":turn_id,
        "status":session.get("status") or "waiting",
    }


OPENAI_AGENTS_SESSION_CAPABILITY_ID="openai.agents.session"
OPENAI_AGENTS_SESSION_EXECUTOR_BINDING=(
    "app.services.openai_agents_runtime_service.execute_openai_agents_session"
)


def execute_openai_agents_session(
    *,
    authorization:Any,
    routing_decision:Any,
    payload:dict[str,Any],
)->Any:
    """Canonical Harness adapter for the subordinate OpenAI Agents runtime."""
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.harness_authorization_service import (
        resolve_harness_authorization,
        validate_harness_authorization,
    )

    auth=resolve_harness_authorization(authorization)
    auth=validate_harness_authorization(
        auth,
        expected_action="EXECUTION",
        expected_subject=f"capability:{OPENAI_AGENTS_SESSION_CAPABILITY_ID}",
    )
    record=GLOBAL_CAPABILITY_REGISTRY.get(OPENAI_AGENTS_SESSION_CAPABILITY_ID)
    if record is None:
        raise PermissionError("OpenAI Agents session capability is not registered")
    if record.executor_binding!=OPENAI_AGENTS_SESSION_EXECUTOR_BINDING:
        raise PermissionError("OpenAI Agents Registry executor mismatch")
    if str(getattr(routing_decision,"selected_capability_id",""))!=OPENAI_AGENTS_SESSION_CAPABILITY_ID:
        raise PermissionError("OpenAI Agents routing capability mismatch")
    if str(getattr(routing_decision,"authorized_action","")).upper()!="EXECUTION":
        raise PermissionError("OpenAI Agents routing action mismatch")
    if str(getattr(routing_decision,"selected_executor_binding",""))!=OPENAI_AGENTS_SESSION_EXECUTOR_BINDING:
        raise PermissionError("OpenAI Agents routing executor mismatch")
    lineage=dict(auth.lineage or {})
    routing_id=str(getattr(routing_decision,"routing_id",""))
    if lineage.get("routing_id")!=routing_id:
        raise PermissionError("OpenAI Agents authorization routing mismatch")
    if lineage.get("capability_id")!=OPENAI_AGENTS_SESSION_CAPABILITY_ID:
        raise PermissionError("OpenAI Agents authorization capability mismatch")
    if lineage.get("selected_executor_binding")!=OPENAI_AGENTS_SESSION_EXECUTOR_BINDING:
        raise PermissionError("OpenAI Agents authorization executor mismatch")

    forbidden={
        "api_key","authorization","authorization_id","transport","client",
        "provider_client","secret","token","access_token","refresh_token",
    }
    if any(str(key).casefold() in forbidden for key in dict(payload or {})):
        raise PermissionError("OpenAI Agents payload attempted to inject authority or secret material")

    # DD2 registers the executable boundary now, but routing remains fail-closed
    # until live WIF/model/session evidence promotes the Registry record.
    if not record.execution_enabled:
        raise PermissionError(
            "EXTERNAL_CONFIGURATION_REQUIRED: OpenAI Agents session capability is not live-proven"
        )

    raise PermissionError(
        "EXTERNAL_CONFIGURATION_REQUIRED: trusted OpenAI Agents live transport is not activated"
    )


class OpenAIAgentsRuntime:
    def __init__(
        self,
        *,
        transport:Any,
        environment_provider:Any|None=None,
    )->None:
        if not callable(transport):
            raise TypeError("OpenAI Agents transport must be callable")
        self.transport=transport
        self.environment_provider=environment_provider

    def create_session(
        self,
        *,
        authorization_ref:str,
        execution_id:str,
        agent_config:Mapping[str,Any],
        environment:Mapping[str,Any],
        initial_input:str,
        trace_refs:tuple[str,...],
        task_id:str|None=None,
        attempt_id:str|None=None,
        runtime_revision:str="dd2-runtime-v1",
        provider:str="openai",
        subagent_refs:tuple[str,...]=(),
        environment_lease:AgentEnvironmentLease|None=None,
        environment_context:Mapping[str,Any]|None=None,
    )->OpenAIAgentSessionReceipt:
        auth=validate_harness_authorization(
            authorization_ref,
            expected_action="EXECUTION",
            expected_subject="capability:openai.agents.session",
            expected_execution_id=execution_id,
        )
        model=str(agent_config.get("model") or "")
        require_registered_openai_model(model)

        environment_payload=dict(environment)
        self_hosted=str(environment_payload.get("type") or "").lower()=="self_hosted"
        if self_hosted:
            if self.environment_provider is None:
                raise PermissionError(
                    "self-hosted OpenAI Agents session requires AgentEnvironmentProvider"
                )
            if environment_lease is None:
                raise PermissionError(
                    "self-hosted OpenAI Agents session requires AgentEnvironmentLease"
                )
            environment_lease.assert_active()
            context=dict(environment_context or {})
            required_context=(
                "mission_id","goal_id","workspace","repo_sha","tree_sha",
            )
            missing=tuple(
                name for name in required_context
                if not str(context.get(name) or "").strip()
            )
            if missing:
                raise ValueError(
                    "self-hosted environment context missing: "+",".join(missing)
                )
            if environment_lease.task_lease_ref!=f"delegated-task:{str(task_id or execution_id)}":
                raise PermissionError(
                    "AgentEnvironmentLease does not bind selected OpenAI task"
                )

        body={
            "agent":dict(agent_config),
            "environment":dict(environment),
            "input":str(initial_input),
            "metadata":{"br_execution_id":execution_id},
        }
        remote=self.transport(
            method="POST",
            path="/agents/sessions",
            body=body,
            idempotency_key=f"br-openai-session:{execution_id}",
        )
        turn=_turn_from_session(remote)
        receipt=OpenAIAgentSessionReceipt.from_api(
            remote,
            turn=turn,
            agent_model=model,
            reasoning_effort=str(
                (agent_config.get("reasoning") or {}).get("effort") or "medium"
            ),
            multi_agent_enabled=bool(
                (agent_config.get("multi_agent") or {}).get("enabled")
            ),
            subagent_count=int(
                (agent_config.get("multi_agent") or {}).get("max_concurrent_subagents") or 0
            ),
            tool_calls=tuple(
                dict(x) for x in (remote.get("tool_calls") or ()) if isinstance(x,Mapping)
            ),
            artifacts=tuple(
                dict(x) for x in (remote.get("artifacts") or ()) if isinstance(x,Mapping)
            ),
            trace_refs=trace_refs,
            task_id=str(task_id or execution_id),
            attempt_id=str(attempt_id or execution_id),
            runtime_revision=runtime_revision,
            provider=provider,
            subagent_refs=subagent_refs,
        )
        from app.database.openai_agents_repository import persist_openai_agent_session_receipt
        persist_openai_agent_session_receipt(receipt)

        # For self-hosted sessions, persist the provider session identity first.
        # Only then bind external compute. The application OpenAI API key remains
        # in the application-side transport and is never passed to the provider.
        if self_hosted:
            from app.services.agent_environment_provider import AgentEnvironmentAcquireRequest
            context=dict(environment_context or {})
            openai_environment_id=str(receipt.environment_id or "").strip()
            if not openai_environment_id:
                raise RuntimeError(
                    "OpenAI self-hosted session omitted environment identity"
                )
            request=AgentEnvironmentAcquireRequest(
                environment_lease=environment_lease,
                mission_id=str(context["mission_id"]),
                goal_id=str(context["goal_id"]),
                task_id=str(task_id or execution_id),
                attempt_id=str(attempt_id or execution_id),
                openai_session_id=receipt.session_id,
                openai_environment_id=openai_environment_id,
                workspace=str(context["workspace"]),
                repo_sha=str(context["repo_sha"]),
                tree_sha=str(context["tree_sha"]),
                mutating=bool(context.get("mutating",False)),
            )
            binding=self.environment_provider.acquire(request)
            binding_ref=f"sprite-binding:{getattr(binding,'binding_id','')}"
            receipt=replace(
                receipt,
                trace_refs=tuple(dict.fromkeys((*receipt.trace_refs,binding_ref))),
                updated_at=_now(),
                revision=receipt.revision+1,
            )
            persist_openai_agent_session_receipt(
                receipt,
                expected_current_revision=1,
            )

        consume_harness_authorization(auth)
        return receipt

    def recover_same_session(
        self,
        session_id:str,
        *,
        prior_turn_id:str|None,
        trace_refs:tuple[str,...],
    )->OpenAIAgentSessionReceipt:
        from app.database.openai_agents_repository import (
            get_openai_agent_session_head,
            persist_openai_agent_session_receipt,
        )
        prior=get_openai_agent_session_head(session_id)
        if prior is None:
            raise LookupError("OpenAI session is not known to BR persistence")
        remote=self.transport(
            method="GET",
            path=f"/agents/sessions/{session_id}",
            body=None,
            idempotency_key=None,
        )
        if str(remote.get("id") or "")!=session_id:
            raise OpenAIAgentsAPIError("OpenAI session recovery identity mismatch")
        turn=_turn_from_session(remote,prior_turn_id)
        receipt=OpenAIAgentSessionReceipt.from_api(
            remote,
            turn=turn,
            agent_model=str(prior["agent_model"]),
            reasoning_effort=str(prior["reasoning_effort"]),
            multi_agent_enabled=bool(prior["multi_agent_enabled"]),
            subagent_count=int(prior["subagent_count"]),
            tool_calls=tuple(
                dict(x) for x in (remote.get("tool_calls") or ()) if isinstance(x,Mapping)
            ),
            artifacts=tuple(
                dict(x) for x in (remote.get("artifacts") or ()) if isinstance(x,Mapping)
            ),
            trace_refs=tuple(dict.fromkeys((*tuple(prior["trace_refs"]),*trace_refs))),
            task_id=str(prior.get("task_id") or "UNBOUND"),
            attempt_id=str(prior.get("attempt_id") or "UNBOUND"),
            runtime_revision=str(prior.get("runtime_revision") or "dd2-runtime-v1"),
            provider=str(prior.get("provider") or "openai"),
            subagent_refs=tuple(prior.get("subagent_refs") or ()),
            revision=int(prior["revision"])+1,
        )
        persist_openai_agent_session_receipt(
            receipt,expected_current_revision=int(prior["revision"])
        )
        return receipt

    def submit_tool_result(
        self,
        *,
        authorization_ref:str,
        execution_id:str,
        session_id:str,
        turn_id:str,
        call_id:str,
        tool_name:str,
        success:bool,
        output:str,
        evidence_refs:tuple[str,...],
    )->dict[str,Any]:
        from app.database.openai_agents_repository import (
            get_openai_tool_result,
            persist_openai_tool_result,
        )
        auth=validate_harness_authorization(
            authorization_ref,
            expected_action="EXECUTION",
            expected_subject="capability:openai.agents.session",
            expected_execution_id=execution_id,
        )
        existing=get_openai_tool_result(session_id,turn_id,call_id)
        if existing is not None:
            candidate=persist_openai_tool_result(
                session_id=session_id,
                turn_id=turn_id,
                call_id=call_id,
                tool_name=tool_name,
                success=success,
                output_json=output,
                evidence_refs=evidence_refs,
            )
            consume_harness_authorization(auth)
            return {**candidate,"accepted":True,"completed":False}
        remote=self.transport(
            method="POST",
            path=f"/agents/sessions/{session_id}/events",
            body={"events":[{
                "type":"agent.session.input.tool_result",
                "turn_id":turn_id,
                "call_id":call_id,
                "success":bool(success),
                "output":str(output),
            }]},
            idempotency_key=f"br-openai-tool-result:{session_id}:{turn_id}:{call_id}",
        )
        saved=persist_openai_tool_result(
            session_id=session_id,
            turn_id=turn_id,
            call_id=call_id,
            tool_name=tool_name,
            success=success,
            output_json=output,
            evidence_refs=evidence_refs,
        )
        consume_harness_authorization(auth)
        return {
            **saved,
            "accepted":bool(remote.get("accepted") or remote.get("_http_status")==202),
            "completed":False,
        }


__all__=[
    "MAX_CONCURRENT_OPENAI_SUBAGENTS",
    "OpenAIAgentsAPIError",
    "OpenAIAgentsRuntime",
    "OPENAI_AGENTS_SESSION_CAPABILITY_ID",
    "OPENAI_AGENTS_SESSION_EXECUTOR_BINDING",
    "execute_openai_agents_session",
    "authorize_openai_execution_scope",
    "build_openai_agent_configuration",
    "build_openai_subagent_plan",
    "build_tool_search_configuration",
    "classify_model_eligibility",
    "classify_openai_session_state",
    "gpt_6_1_sol_profile",
    "require_bounded_computer_use",
    "require_registered_openai_model",
    "validate_application_secret_isolation",
    "verify_openai_task_completion",
]
