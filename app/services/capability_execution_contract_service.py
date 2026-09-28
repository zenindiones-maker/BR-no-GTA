from __future__ import annotations
from typing import Any

CAN_SEMANTIC_REASONING = "CAN_SEMANTIC_REASONING"
CAN_READ_REPOSITORY = "CAN_READ_REPOSITORY"
CAN_WRITE_REPOSITORY = "CAN_WRITE_REPOSITORY"
CAN_RUN_TESTS = "CAN_RUN_TESTS"
CAN_RUN_BENCHMARK = "CAN_RUN_BENCHMARK"
CAN_MUTATE_CANDIDATE = "CAN_MUTATE_CANDIDATE"
CAN_REVIEW = "CAN_REVIEW"
CAN_CONSUME_ARTIFACT_REFS = "CAN_CONSUME_ARTIFACT_REFS"
CAN_PRODUCE_ARTIFACT_REFS = "CAN_PRODUCE_ARTIFACT_REFS"

# Typed effects/surfaces/output contracts are orthogonal to risk and execution
# operations. They extend the canonical capability contract rather than
# replacing side_effect_class or execution_operations.
EFFECT_HUMAN_MESSAGE_DELIVERY = "HUMAN_MESSAGE_DELIVERY"
SURFACE_TELEGRAM_GROUP = "telegram_group"
OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1 = "TelegramDeliveryReceipt/v1"
OUTPUT_CONTRACT_YOUTUBE_SPECIALIST_RESULT_V1 = "YouTubeSpecialistResult/v1"
OUTPUT_CONTRACT_EDITORIAL_SCRIPT_BUNDLE_V1 = "EditorialScriptBundle/v1"
OUTPUT_CONTRACT_SCRIPT_REVIEW_RESULT_V1 = "ScriptReviewResult/v1"

ALL_EXECUTION_OPERATIONS = frozenset({
    CAN_SEMANTIC_REASONING,
    CAN_READ_REPOSITORY,
    CAN_WRITE_REPOSITORY,
    CAN_RUN_TESTS,
    CAN_RUN_BENCHMARK,
    CAN_MUTATE_CANDIDATE,
    CAN_REVIEW,
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_PRODUCE_ARTIFACT_REFS,
})


EXECUTION_KIND_ORCHESTRATOR = "ORCHESTRATOR"
EXECUTION_KIND_SEMANTIC_REASONER = "SEMANTIC_REASONER"
EXECUTION_KIND_DETERMINISTIC_ANALYSIS_AGENT = "DETERMINISTIC_ANALYSIS_AGENT"
EXECUTION_KIND_TOOL = "TOOL"
EXECUTION_KIND_DETERMINISTIC_WORKER = "DETERMINISTIC_WORKER"
EXECUTION_KIND_INDEPENDENT_REVIEWER = "INDEPENDENT_REVIEWER"
EXECUTION_KIND_MUTATION_EXECUTOR = "MUTATION_EXECUTOR"
EXECUTION_KIND_VALIDATOR = "VALIDATOR"
EXECUTION_KIND_PROVIDER = "PROVIDER"
EXECUTION_KIND_PRESENTATION = "PRESENTATION"


_CANONICAL_ROLE_BY_TASK_CLASS = {
    "evidence-collection": "EVIDENCE",
    "incident-diagnosis": "DIAGNOSIS",
    "root-cause-analysis": "ROOT_CAUSE",
    "recovery-proposal": "PROPOSAL",
    "independent-review": "REVIEW",
    "recovery-apply": "APPLY",
    "apply-recovery": "APPLY",
    "recovery-validation": "VALIDATE",
    "validate-recovery": "VALIDATE",
    "presentation": "PRESENTATION",
}

_CANONICAL_ROLE_BY_OUTPUT = {
    "IncidentEvidenceBundle": "EVIDENCE",
    "IncidentDiagnosisEvidence": "DIAGNOSIS",
    "RootCauseEvidence": "ROOT_CAUSE",
    "RecoveryProposalEvidence": "PROPOSAL",
    "IndependentReviewEvidence": "REVIEW",
    "RecoveryApplyReceipt": "APPLY",
    "RecoveryValidationReceipt": "VALIDATE",
    OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1: "PRESENTATION",
}

_CANONICAL_ROLE_OPERATIONS = {
    "EVIDENCE": frozenset({
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "DIAGNOSIS": frozenset({
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "ROOT_CAUSE": frozenset({
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "PROPOSAL": frozenset({
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "REVIEW": frozenset({
        CAN_REVIEW,
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "APPLY": frozenset({
        CAN_READ_REPOSITORY,
        CAN_WRITE_REPOSITORY,
        CAN_MUTATE_CANDIDATE,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "VALIDATE": frozenset({
        CAN_READ_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "PRESENTATION": frozenset({
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "EDITORIAL_GENERATION": frozenset({
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
    "EDITORIAL_REVIEW": frozenset({
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }),
}


def _editorial_contract_role(requirement: dict[str, Any]) -> str | None:
    action = str(
        requirement.get("action")
        or requirement.get("authorized_action")
        or ""
    ).strip().upper()
    if action != "EDITORIAL":
        return None
    task_class = str(
        requirement.get("task_class") or ""
    ).strip().casefold()
    text = " ".join(
        str(requirement.get(key) or "").strip().casefold()
        for key in (
            "task_id",
            "task_class",
            "objective",
            "query",
            "required_capability_description",
            "expected_output",
        )
    )
    script_markers = (
        "script",
        "scriptspec",
        "script spec",
        "contentitem",
        "content item",
        "roteiro",
    )
    has_script_contract = any(marker in text for marker in script_markers)
    if not has_script_contract:
        return None
    review_markers = ("review", "reviewer", "revis", "critique")
    if "review" in task_class or any(
        marker in text for marker in review_markers
    ):
        return "EDITORIAL_REVIEW"
    generation_markers = (
        "produce",
        "generate",
        "create",
        "write",
        "natural pt-br script",
        "ready for production planning",
        "produzir",
        "gerar",
        "escrever",
    )
    if task_class == "editorial" or any(
        marker in text for marker in generation_markers
    ):
        return "EDITORIAL_GENERATION"
    return None


def infer_functional_role(requirement: dict[str, Any]) -> str:
    explicit = str(
        requirement.get("functional_role") or ""
    ).strip().upper()
    if explicit == "IMPLEMENT":
        task_class = str(
            requirement.get("task_class") or ""
        ).strip().casefold()
        required_operations = {
            str(item).strip()
            for item in (requirement.get("required_operations") or ())
            if str(item).strip()
        }
        if (
            task_class in {
                "bounded-development",
                "adaptive-code-change",
                "recovery-apply",
                "apply-recovery",
            }
            or CAN_MUTATE_CANDIDATE in required_operations
            or CAN_WRITE_REPOSITORY in required_operations
        ):
            # IMPLEMENT is a legacy planner label. Canonical mutating work is
            # APPLY; keep the alias bounded to contracts that really mutate.
            return "APPLY"
    if explicit and explicit != "GENERAL":
        return explicit
    editorial_role = _editorial_contract_role(requirement)
    if editorial_role:
        return editorial_role
    expected_output = str(
        requirement.get("expected_output") or ""
    ).strip()
    if expected_output in _CANONICAL_ROLE_BY_OUTPUT:
        return _CANONICAL_ROLE_BY_OUTPUT[expected_output]

    task_class = str(
        requirement.get("task_class") or ""
    ).strip().casefold()
    mission_policy_class = str(
        requirement.get("mission_policy_class") or ""
    ).strip().upper()
    if (
        mission_policy_class == "SYSTEM_IMPROVEMENT"
        and task_class in _CANONICAL_ROLE_BY_TASK_CLASS
    ):
        return _CANONICAL_ROLE_BY_TASK_CLASS[task_class]
    return "GENERAL"


def _is_editorial_review_requirement(requirement: dict[str, Any]) -> bool:
    return _editorial_contract_role(requirement) == "EDITORIAL_REVIEW"


def infer_required_output_contract_ids(
    requirement: dict[str, Any],
) -> tuple[str, ...]:
    explicit = tuple(
        str(item).strip()
        for item in (
            requirement.get("required_output_contract_ids") or ()
        )
        if str(item).strip()
    )
    if explicit:
        return explicit
    role = infer_functional_role(requirement)
    if role == "EDITORIAL_GENERATION":
        return (OUTPUT_CONTRACT_EDITORIAL_SCRIPT_BUNDLE_V1,)
    if role == "EDITORIAL_REVIEW":
        return (OUTPUT_CONTRACT_SCRIPT_REVIEW_RESULT_V1,)
    return ()


def infer_required_execution_kind(
    requirement: dict[str, Any],
) -> str | None:
    explicit = str(
        requirement.get("required_execution_kind") or ""
    ).strip().upper()
    if explicit:
        return explicit

    role = infer_functional_role(requirement)
    role_map = {
        "EVIDENCE": EXECUTION_KIND_DETERMINISTIC_WORKER,
        "DIAGNOSIS": EXECUTION_KIND_SEMANTIC_REASONER,
        "ROOT_CAUSE": EXECUTION_KIND_SEMANTIC_REASONER,
        "PROPOSAL": EXECUTION_KIND_SEMANTIC_REASONER,
        "REVIEW": EXECUTION_KIND_INDEPENDENT_REVIEWER,
        "APPLY": EXECUTION_KIND_MUTATION_EXECUTOR,
        "VALIDATE": EXECUTION_KIND_VALIDATOR,
        "PRESENTATION": EXECUTION_KIND_PRESENTATION,
        "EDITORIAL_GENERATION": EXECUTION_KIND_SEMANTIC_REASONER,
        "EDITORIAL_REVIEW": EXECUTION_KIND_SEMANTIC_REASONER,
    }
    if role == "REVIEW" and _is_editorial_review_requirement(requirement):
        # Editorial/script review is a YouTube domain task, not the
        # independent engineering reviewer role used by system-improvement.
        role = "EDITORIAL_REVIEW"
    if role in role_map:
        return role_map[role]

    task_class = str(
        requirement.get("task_class") or ""
    ).strip().casefold()
    operations = {
        str(item).strip()
        for item in (requirement.get("required_operations") or ())
        if str(item).strip()
    }
    deterministic_analysis_markers = (
        "repository-analysis",
        "repository-profile",
        "deterministic-analysis",
        "read-only-repository-analysis",
        "readonly-repository-analysis",
    )
    if any(marker in task_class for marker in deterministic_analysis_markers):
        return EXECUTION_KIND_DETERMINISTIC_ANALYSIS_AGENT
    if (
        CAN_MUTATE_CANDIDATE in operations
        or CAN_WRITE_REPOSITORY in operations
    ):
        return EXECUTION_KIND_MUTATION_EXECUTOR
    if CAN_REVIEW in operations:
        return EXECUTION_KIND_INDEPENDENT_REVIEWER
    if CAN_SEMANTIC_REASONING in operations:
        return EXECUTION_KIND_SEMANTIC_REASONER
    if CAN_RUN_TESTS in operations:
        return EXECUTION_KIND_VALIDATOR
    return None


def record_execution_kind(record: Any) -> str:
    resolved = str(
        getattr(record, "resolved_execution_kind", "")
        or getattr(record, "execution_kind", "")
        or ""
    ).strip().upper()
    return resolved or "DETERMINISTIC_WORKER"


def execution_kind_rejection(
    record: Any,
    required_execution_kind: str | None,
) -> str | None:
    required = str(required_execution_kind or "").strip().upper()
    if not required:
        return None
    observed = record_execution_kind(record)
    if observed != required:
        return (
            "execution-kind-incompatible:"
            f"required={required}:observed={observed}"
        )
    return None


def functional_role_rejection(
    record: Any,
    required_functional_role: str | None,
) -> str | None:
    required = str(required_functional_role or "").strip().upper()
    if not required or required == "GENERAL":
        return None
    supported = {
        str(item).strip().upper()
        for item in (getattr(record, "functional_roles", ()) or ())
        if str(item).strip()
    }
    if supported and required not in supported:
        return (
            "functional-role-incompatible:"
            f"required={required}:supported={','.join(sorted(supported))}"
        )
    return None


def functional_role_required_operations(
    requirement: dict[str, Any],
) -> tuple[str, ...] | None:
    role = infer_functional_role(requirement)
    if role == "REVIEW" and _is_editorial_review_requirement(requirement):
        # Let the textual/editorial contract derive the least-privilege
        # operations. In particular, do not inject CAN_REVIEW merely because
        # the human-facing role label is REVIEW.
        return None
    operations = _CANONICAL_ROLE_OPERATIONS.get(role)
    if operations is None:
        return None
    effective = set(operations)
    if role == "EVIDENCE":
        effective.discard(CAN_CONSUME_ARTIFACT_REFS)
        if (
            tuple(requirement.get("input_refs") or ())
            or tuple(requirement.get("dependencies") or ())
            or str(
                requirement.get("mission_policy_class") or ""
            ).strip().upper() == "SYSTEM_IMPROVEMENT"
        ):
            effective.add(CAN_CONSUME_ARTIFACT_REFS)
    return tuple(sorted(effective))

def _blob(requirement: dict[str, Any]) -> str:
    parts = [
        requirement.get("task_id"),
        requirement.get("task_class"),
        requirement.get("objective"),
        requirement.get("query"),
        requirement.get("required_capability_description"),
        requirement.get("expected_output"),
        " ".join(str(x) for x in requirement.get("acceptance_criteria") or ()),
    ]
    return " ".join(str(x or "") for x in parts).casefold()

def derive_required_operations(requirement: dict[str, Any]) -> tuple[str, ...]:
    role_operations = functional_role_required_operations(requirement)
    if role_operations is not None:
        return role_operations

    task_class = str(requirement.get("task_class") or "").strip().casefold()
    if task_class in {"fact-check", "source-verification"}:
        # These are bounded deterministic evidence assessors. Their executor
        # consumes caller-supplied claim/evidence values while the Harness/
        # Hermes layer preserves TaskResultEnvelope lineage around the call.
        # Do not falsely require the capability itself to read/write artifact
        # refs merely because the mission task has dependencies.
        return ()

    if task_class in {"production-planning", "production-plan"}:
        # ProductionPlan materialization is a deterministic artifact transform.
        # The semantic planner may describe the task, but the task executor does
        # not need model reasoning: it consumes a typed ContentItem/ScriptSpec
        # lineage and persists a typed ProductionPlan.
        return tuple(sorted({
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        }))

    text = _blob(requirement)
    normalized_text = text.replace("-", " ").replace("_", " ")
    operations: set[str] = {CAN_PRODUCE_ARTIFACT_REFS}
    dependencies = tuple(requirement.get("dependencies") or ())
    if dependencies:
        operations.add(CAN_CONSUME_ARTIFACT_REFS)

    candidate_markers = (
        "candidate patch",
        "candidate diff",
        "patch diff",
        "local candidate",
        "candidate commit",
        "code candidate",
    )
    candidate_action_markers = (
        "implement",
        "create",
        "build",
        "produce",
        "apply",
        "write",
        "modify",
        "change",
        "fix",
    )
    candidate_mutation_context_markers = (
        "patch",
        "diff",
        "repository",
        "source code",
        "codebase",
        "file change",
        "commit",
        "implementation",
        "refactor",
        "software",
    )
    benchmark_markers = (
        "benchmark", "baseline_ms", "candidate_ms", "wall clock",
        "latency reduction", "comparison report", "compare baseline",
    )
    review_markers = (
        "independent review", "review verdict", "approve/request-changes",
        "request-changes", "code review",
    )
    profile_markers = (
        "latency profile", "profile", "instrument", "call counts",
        "context sizes", "duplicate-call map", "repository inspection",
    )
    reasoning_markers = (
        "root cause", "root-cause", "analyze", "analysis", "diagnose",
        "diagnosis", "reasoning", "causal", "propose", "proposal",
        "synthesize", "synthesis", "interpret",
        "causa raiz", "causa-raiz", "analisar", "análise", "analise",
        "diagnosticar", "diagnóstico", "diagnostico", "propor", "proposta",
        "sintetizar", "síntese", "sintese", "interpretar",
    )
    deterministic_evidence_classes = {
        "evidence-collection",
        "fresh-evidence-collection",
        "knowledge-retrieval",
        "fact-check",
        "source-verification",
    }
    deterministic_evidence_markers = (
        "collect fresh evidence",
        "collect evidence",
        "evidence collection",
        "retrieve knowledge",
        "knowledge retrieval",
        "fact-check",
        "fact check",
        "source verification",
        "source packet",
    )

    task_class = str(requirement.get("task_class") or "").strip().casefold()
    candidate_mutation = (
        task_class in {"bounded-development", "adaptive-code-change"}
        or any(marker in normalized_text for marker in candidate_markers)
        or (
            "candidate" in normalized_text
            and any(
                marker in normalized_text
                for marker in candidate_action_markers
            )
            and any(
                marker in normalized_text
                for marker in candidate_mutation_context_markers
            )
        )
    )
    if candidate_mutation:
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_WRITE_REPOSITORY,
            CAN_RUN_TESTS,
            CAN_MUTATE_CANDIDATE,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in benchmark_markers):
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_RUN_BENCHMARK,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    editorial_review_task = (
        "review" in task_class
        and any(
            marker in normalized_text
            for marker in (
                "script",
                "roteiro",
                "youtube",
                "editorial",
                "content",
                "conteudo",
                "conteúdo",
            )
        )
    )
    if (
        any(marker in text for marker in review_markers)
        and not editorial_review_task
    ):
        operations.update({
            CAN_REVIEW,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in profile_markers):
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    semantic_task = (
        task_class == "semantic"
        or task_class.startswith("semantic-")
        or task_class.endswith("-semantic")
    )
    if semantic_task or any(marker in text for marker in reasoning_markers):
        operations.add(CAN_SEMANTIC_REASONING)

    deterministic_evidence_task = (
        task_class in deterministic_evidence_classes
        or any(marker in normalized_text for marker in deterministic_evidence_markers)
    )
    if (
        operations == {CAN_PRODUCE_ARTIFACT_REFS}
        and not deterministic_evidence_task
    ):
        operations.add(CAN_SEMANTIC_REASONING)
    return tuple(sorted(operations))

def effective_candidate_requirement(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    operations = set(required_operations)
    if CAN_MUTATE_CANDIDATE in operations:
        normalized = str(declared or "REQUIRED").strip().upper()
        return (
            normalized
            if normalized in {"REQUIRED", "CONDITIONAL"}
            else "REQUIRED"
        )
    return "NOT_APPLICABLE"

def effective_side_effect_class(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    operations = set(required_operations)
    if (
        CAN_MUTATE_CANDIDATE in operations
        or CAN_WRITE_REPOSITORY in operations
    ):
        return "BOUNDED_MUTATION"
    return "READ_ONLY"

def capability_execution_contract_rejection(
    record: Any,
    required_operations: tuple[str, ...] | list[str],
) -> str | None:
    required = {str(x).strip() for x in required_operations if str(x).strip()}
    supported = {
        str(x).strip()
        for x in getattr(record, "execution_operations", ()) or ()
        if str(x).strip()
    }
    missing = sorted(required - supported)
    if missing:
        return "execution-contract-insufficient:missing=" + ",".join(missing)
    return None


def capability_required_effects_rejection(
    record: Any,
    required_effects: tuple[str, ...] | list[str],
) -> str | None:
    required = {
        str(item).strip()
        for item in required_effects
        if str(item).strip()
    }
    supported = {
        str(item).strip()
        for item in (getattr(record, "execution_effects", ()) or ())
        if str(item).strip()
    }
    missing = sorted(required - supported)
    if missing:
        return "required-effect-mismatch:missing=" + ",".join(missing)
    return None


def capability_required_surfaces_rejection(
    record: Any,
    required_surfaces: tuple[str, ...] | list[str],
) -> str | None:
    required = {
        str(item).strip()
        for item in required_surfaces
        if str(item).strip()
    }
    supported = {
        str(item).strip()
        for item in (getattr(record, "execution_surfaces", ()) or ())
        if str(item).strip()
    }
    missing = sorted(required - supported)
    if missing:
        return "surface-mismatch:missing=" + ",".join(missing)
    return None


def capability_output_contract_rejection(
    record: Any,
    required_output_contract_ids: tuple[str, ...] | list[str],
) -> str | None:
    required = {
        str(item).strip()
        for item in required_output_contract_ids
        if str(item).strip()
    }
    supported = {
        str(item).strip()
        for item in (getattr(record, "output_contract_ids", ()) or ())
        if str(item).strip()
    }
    missing = sorted(required - supported)
    if missing:
        return "output-contract-mismatch:missing=" + ",".join(missing)
    return None


def capability_side_effect_class_rejection(
    record: Any,
    required_side_effect_class: str | None,
) -> str | None:
    required = str(required_side_effect_class or "").strip().upper()
    if not required or required in {"LOW", "MEDIUM", "HIGH"}:
        return None
    observed = str(
        getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
    ).strip().upper()
    write_scope = tuple(
        getattr(record, "default_write_scope", ()) or ()
    )
    if required == "READ_ONLY":
        if observed in {
            "EXTERNAL_SIDE_EFFECT",
            "BOUNDED_MUTATION",
            "MUTATING",
        } or write_scope:
            return (
                "side-effect-authorization-mismatch:"
                f"required=READ_ONLY:observed={observed}"
            )
        return None
    if required == "EXTERNAL_SIDE_EFFECT":
        if observed != "EXTERNAL_SIDE_EFFECT":
            return (
                "side-effect-authorization-mismatch:"
                f"required=EXTERNAL_SIDE_EFFECT:observed={observed}"
            )
        return None
    if required in {"BOUNDED_MUTATION", "MUTATING"}:
        if observed not in {"BOUNDED_MUTATION", "MUTATING"} and not write_scope:
            return (
                "side-effect-authorization-mismatch:"
                f"required={required}:observed={observed}"
            )
        return None
    if observed != required:
        return (
            "side-effect-authorization-mismatch:"
            f"required={required}:observed={observed}"
        )
    return None
