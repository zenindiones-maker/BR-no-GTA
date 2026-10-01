from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _content_sha256(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(dict(value))).hexdigest()


def _text(value: Any, name: str, maximum: int = 2000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


def _tuple(value: Sequence[Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(dict.fromkeys(_text(item, "item") for item in value))


@dataclass(frozen=True)
class AgentTaskEvalCase:
    case_id: str
    title: str
    source_family: str
    task_class: str
    eval_class: str
    grader_type: str
    expected_outcomes: tuple[str, ...]
    deterministic_checks: tuple[str, ...]
    semantic_criterion: str | None
    critical: bool
    evidence_refs: tuple[str, ...]
    required_tool_sequence: tuple[str, ...]
    content_sha256: str
    schema: str = "AgentTaskEvalCase/v1"

    @classmethod
    def create(
        cls,
        *,
        case_id: str,
        title: str,
        source_family: str,
        task_class: str,
        eval_class: str,
        grader_type: str,
        expected_outcomes: Sequence[str],
        deterministic_checks: Sequence[str] = (),
        semantic_criterion: str | None = None,
        critical: bool = False,
        evidence_refs: Sequence[str] = (),
        required_tool_sequence: Sequence[str] = (),
    ) -> "AgentTaskEvalCase":
        eval_class = _text(eval_class, "eval_class", 64).upper()
        if eval_class not in {"CAPABILITY_EVAL", "REGRESSION_EVAL"}:
            raise ValueError("unsupported eval_class")
        grader_type = _text(grader_type, "grader_type", 64).upper()
        if grader_type not in {"DETERMINISTIC", "MODEL"}:
            raise ValueError("unsupported grader_type")
        expected = _tuple(expected_outcomes)
        if not expected:
            raise ValueError("expected_outcomes are required")
        checks = _tuple(deterministic_checks)
        semantic = str(semantic_criterion or "").strip() or None
        if grader_type == "DETERMINISTIC" and not checks:
            raise ValueError("deterministic grader requires deterministic_checks")
        if grader_type == "DETERMINISTIC" and semantic is not None:
            raise ValueError("deterministic grader cannot require semantic criterion")
        if grader_type == "MODEL" and semantic is None:
            raise ValueError("model grader requires semantic_criterion")
        base = {
            "case_id": _text(case_id, "case_id", 192),
            "title": _text(title, "title", 500),
            "source_family": _text(source_family, "source_family", 128).upper(),
            "task_class": _text(task_class, "task_class", 192).upper(),
            "eval_class": eval_class,
            "grader_type": grader_type,
            "expected_outcomes": expected,
            "deterministic_checks": checks,
            "semantic_criterion": semantic,
            "critical": bool(critical),
            "evidence_refs": _tuple(evidence_refs),
            "required_tool_sequence": _tuple(required_tool_sequence),
            "schema": "AgentTaskEvalCase/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k != "schema"},
            content_sha256=_content_sha256(base),
        )


@dataclass(frozen=True)
class AgentTaskEvalSuite:
    suite_id: str
    cases: tuple[AgentTaskEvalCase, ...]
    created_at: str
    content_sha256: str
    schema: str = "AgentTaskEvalSuite/v1"

    @classmethod
    def create(
        cls,
        *,
        suite_id: str,
        cases: Sequence[AgentTaskEvalCase],
        created_at: str | None = None,
    ) -> "AgentTaskEvalSuite":
        rows = tuple(cases)
        if not rows:
            raise ValueError("eval suite requires cases")
        ids = [row.case_id for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("eval suite case_id values must be unique")
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        base = {
            "suite_id": _text(suite_id, "suite_id", 192),
            "case_digests": tuple(row.content_sha256 for row in rows),
            "created_at": stamp,
            "schema": "AgentTaskEvalSuite/v1",
        }
        return cls(
            suite_id=base["suite_id"],
            cases=rows,
            created_at=stamp,
            content_sha256=_content_sha256(base),
        )


@dataclass(frozen=True)
class AgentTaskTrial:
    trial_id: str
    case_id: str
    worker_id: str
    worker_version: str
    runtime_version: str
    observed_outcomes: tuple[str, ...]
    deterministic_results: dict[str, bool]
    model_grade: float | None
    wall_clock_ms: int
    tool_calls: int
    context_bytes: int
    human_corrections: int
    critical_regression: bool
    model_version: str | None
    content_sha256: str
    schema: str = "AgentTaskTrial/v1"

    @classmethod
    def create(
        cls,
        *,
        trial_id: str,
        case_id: str,
        worker_id: str,
        worker_version: str,
        runtime_version: str,
        observed_outcomes: Sequence[str],
        deterministic_results: Mapping[str, bool],
        model_grade: float | None,
        wall_clock_ms: int,
        tool_calls: int,
        context_bytes: int,
        human_corrections: int,
        critical_regression: bool,
        model_version: str | None = None,
    ) -> "AgentTaskTrial":
        for name, value in (
            ("wall_clock_ms", wall_clock_ms),
            ("tool_calls", tool_calls),
            ("context_bytes", context_bytes),
            ("human_corrections", human_corrections),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if model_grade is not None and not 0.0 <= float(model_grade) <= 1.0:
            raise ValueError("model_grade must be between 0 and 1")
        base = {
            "trial_id": _text(trial_id, "trial_id", 192),
            "case_id": _text(case_id, "case_id", 192),
            "worker_id": _text(worker_id, "worker_id", 192),
            "worker_version": _text(worker_version, "worker_version", 192),
            "runtime_version": _text(runtime_version, "runtime_version", 192),
            "observed_outcomes": _tuple(observed_outcomes),
            "deterministic_results": {
                str(k): bool(v) for k, v in deterministic_results.items()
            },
            "model_grade": None if model_grade is None else float(model_grade),
            "wall_clock_ms": wall_clock_ms,
            "tool_calls": tool_calls,
            "context_bytes": context_bytes,
            "human_corrections": human_corrections,
            "critical_regression": bool(critical_regression),
            "model_version": str(model_version or "").strip() or None,
            "schema": "AgentTaskTrial/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k != "schema"},
            content_sha256=_content_sha256(base),
        )


@dataclass(frozen=True)
class AgentTaskTrialGrade:
    trial_id: str
    case_id: str
    verified_outcome: bool
    promotion_eligible: bool
    critical_regression: bool
    grade_source: str
    reasons: tuple[str, ...]
    schema: str = "AgentTaskTrialGrade/v1"


def grade_trial(
    case: AgentTaskEvalCase,
    trial: AgentTaskTrial,
    *,
    model_accept_threshold: float = 0.75,
) -> AgentTaskTrialGrade:
    if trial.case_id != case.case_id:
        raise ValueError("trial/case identity mismatch")
    reasons: list[str] = []
    expected_present = set(case.expected_outcomes).issubset(set(trial.observed_outcomes))
    if not expected_present:
        reasons.append("EXPECTED_OUTCOME_MISSING")
    if case.grader_type == "DETERMINISTIC":
        checks_ok = all(
            trial.deterministic_results.get(check) is True
            for check in case.deterministic_checks
        )
        if not checks_ok:
            reasons.append("DETERMINISTIC_CHECK_FAILED")
        verified = bool(expected_present and checks_ok)
        source = "DETERMINISTIC"
    else:
        accepted = (
            trial.model_grade is not None
            and float(trial.model_grade) >= float(model_accept_threshold)
        )
        if not accepted:
            reasons.append("SEMANTIC_GRADE_BELOW_THRESHOLD")
        verified = bool(expected_present and accepted)
        source = "MODEL"
    if trial.critical_regression:
        reasons.append("CRITICAL_REGRESSION")
        verified = False
    promotion = bool(verified and not trial.critical_regression)
    return AgentTaskTrialGrade(
        trial_id=trial.trial_id,
        case_id=case.case_id,
        verified_outcome=verified,
        promotion_eligible=promotion,
        critical_regression=trial.critical_regression,
        grade_source=source,
        reasons=tuple(reasons),
    )


def _det(
    case_id: str,
    title: str,
    family: str,
    task_class: str,
    eval_class: str,
    outcomes: Sequence[str],
    checks: Sequence[str],
    *,
    critical: bool = False,
    refs: Sequence[str] = (),
) -> AgentTaskEvalCase:
    return AgentTaskEvalCase.create(
        case_id=case_id,
        title=title,
        source_family=family,
        task_class=task_class,
        eval_class=eval_class,
        grader_type="DETERMINISTIC",
        expected_outcomes=outcomes,
        deterministic_checks=checks,
        critical=critical,
        evidence_refs=refs,
    )


def _model(
    case_id: str,
    title: str,
    family: str,
    task_class: str,
    eval_class: str,
    outcomes: Sequence[str],
    criterion: str,
    *,
    refs: Sequence[str] = (),
) -> AgentTaskEvalCase:
    return AgentTaskEvalCase.create(
        case_id=case_id,
        title=title,
        source_family=family,
        task_class=task_class,
        eval_class=eval_class,
        grader_type="MODEL",
        expected_outcomes=outcomes,
        semantic_criterion=criterion,
        critical=False,
        evidence_refs=refs,
    )


def build_foundation_eval_suite() -> AgentTaskEvalSuite:
    # These are real BR-no-GTA task classes/incidents.  The first nine are
    # grounded in the canonical root-suite failure capture from 2026-09-30.
    cases: list[AgentTaskEvalCase] = [
        _det(
            "root-pronunciation-vice-city",
            "Vice City target sound preserves pt-BR synthesis chunk",
            "ROOT_SUITE_FAILURE",
            "AUDIO_PRONUNCIATION_REGRESSION",
            "REGRESSION_EVAL",
            ("pt-BR locale retained", "target synthesis has no leaked punctuation"),
            ("locale_pt_br", "target_text_exact"),
            critical=True,
            refs=("tests/test_character_name_pronunciation_candidate.py::test_vice_city_target_sound_does_not_create_foreign_language_chunk",),
        ),
        _det(
            "root-claude-auth-boundary",
            "Claude workflow auth boundary maps only approved repository secret",
            "ROOT_SUITE_FAILURE",
            "AUTH_BOUNDARY_REGRESSION",
            "REGRESSION_EVAL",
            ("workflow auth boundary matches repository policy", "no prompt/model call in validation gate"),
            ("secret_mapping_valid", "no_model_call"),
            critical=True,
            refs=("tests/test_claude_auth_boundary.py::ClaudeAuthBoundaryTests::test_workflow_maps_only_repository_secrets_and_runs_no_prompt",),
        ),
        _det(
            "root-recovery-manifest-audio",
            "Recovery manifest remains forward-only and audio fingerprinted",
            "ROOT_SUITE_FAILURE",
            "RECOVERY_MANIFEST_REGRESSION",
            "REGRESSION_EVAL",
            ("manifest builds", "audio fingerprint valid", "forward-only recovery preserved"),
            ("manifest_builds", "audio_fingerprint_valid", "forward_only"),
            critical=True,
            refs=("tests/test_recovery_manifest_service.py::test_recovery_manifest_is_forward_only_and_audio_fingerprinted",),
        ),
        _det(
            "root-recovery-final-delivery",
            "Recovery manifest records private YouTube and Telegram milestone",
            "ROOT_SUITE_FAILURE",
            "RECOVERY_DELIVERY_REGRESSION",
            "REGRESSION_EVAL",
            ("private YouTube milestone preserved", "Telegram delivery milestone preserved"),
            ("youtube_private_checkpoint", "telegram_checkpoint"),
            critical=True,
            refs=("tests/test_recovery_manifest_service.py::test_recovery_manifest_records_final_private_youtube_and_telegram_milestone",),
        ),
        _det(
            "root-longform-controller",
            "Longform bridge runs editorial controller before official render worker",
            "ROOT_SUITE_FAILURE",
            "PRODUCTION_ORDERING_REGRESSION",
            "REGRESSION_EVAL",
            ("editorial controller precedes render worker",),
            ("workflow_order_valid",),
            critical=True,
            refs=("tests/test_run001_longform_editorial_controller.py::test_video_a_live_bridge_runs_editorial_controller_then_official_render_worker",),
        ),
        _det(
            "root-current-audio-contract",
            "Current audio contract matches canonical official voice identity",
            "ROOT_SUITE_FAILURE",
            "AUDIO_CONTRACT_REGRESSION",
            "REGRESSION_EVAL",
            ("official voice contract consistent with canonical state",),
            ("audio_contract_consistent",),
            critical=True,
            refs=("tests/test_video_a_current_contract_e2e.py::test_current_audio_contract_hash_and_voice_are_pinned",),
        ),
        _det(
            "root-final-audio-approval",
            "Human approved final end signature artifact is materialized",
            "ROOT_SUITE_FAILURE",
            "AUDIO_APPROVAL_REGRESSION",
            "REGRESSION_EVAL",
            ("approval artifact exists", "approval digest valid"),
            ("approval_exists", "approval_digest_valid"),
            critical=True,
            refs=("tests/test_video_a_final_audio_approval.py::test_g_brand_mixed_is_locked_as_human_approved_final_end_signature",),
        ),
        _det(
            "root-video-readiness",
            "Static readiness preserves editorial status while failing unavailable audio/visual gates",
            "ROOT_SUITE_FAILURE",
            "READINESS_REGRESSION",
            "REGRESSION_EVAL",
            ("readiness report materializes", "editorial remains green", "missing audio/visual fail closed"),
            ("report_builds", "editorial_preserved", "audio_visual_fail_closed"),
            critical=True,
            refs=("tests/test_video_a_production_readiness.py::test_static_readiness_preserves_green_editorial_but_fails_audio_and_visual",),
        ),
        _det(
            "root-voice-cleanliness",
            "Legacy voice artifacts are absent from current-tree operational surfaces",
            "ROOT_SUITE_FAILURE",
            "VOICE_RUNTIME_CLEANLINESS",
            "REGRESSION_EVAL",
            ("legacy runtime references absent",),
            ("legacy_reference_scan_clean",),
            critical=True,
            refs=("tests/test_voice_runtime_cleanliness.py::test_legacy_voice_artifacts_and_references_are_absent_from_current_tree",),
        ),
        _det(
            "telegram-semantic-binding",
            "Telegram document question binds exact normalized document content",
            "TELEGRAM_SEMANTIC_RECOVERY",
            "TELEGRAM_SEMANTIC_BINDING",
            "REGRESSION_EVAL",
            ("document content bound to semantic request", "human need not repeat question"),
            ("input_binding_exact", "question_replay_not_required"),
            critical=True,
            refs=("telegram semantic conversation recovery incident",),
        ),
        _det(
            "telegram-provider-fallback",
            "Telegram semantic answer survives first provider failure",
            "TELEGRAM_SEMANTIC_RECOVERY",
            "TELEGRAM_PROVIDER_RECOVERY",
            "CAPABILITY_EVAL",
            ("semantic answer delivered after provider failure",),
            ("fallback_result_delivered",),
            refs=("telegram semantic recovery incident",),
        ),
        _det(
            "provider-503-wait-requeue",
            "Provider 503 transitions to durable availability wait and causal requeue",
            "PROVIDER_503_RECOVERY",
            "PROVIDER_AVAILABILITY_RECOVERY",
            "REGRESSION_EVAL",
            ("WAITING_FOR_PROVIDER_AVAILABILITY", "no blind replan", "event-driven wake"),
            ("wait_state", "no_blind_replan", "wake_condition_bound"),
            critical=True,
            refs=("provider 503 recovery",),
        ),
        _det(
            "durable-resume-partial",
            "Durable V3 resumes partial failure without replaying completed work",
            "DURABLE_V3_RESUME",
            "DURABLE_PARTIAL_RESUME",
            "REGRESSION_EVAL",
            ("completed work no-op", "next incomplete task resumes"),
            ("completed_replay_noop", "partial_resume"),
            critical=True,
            refs=("Durable V3 partial-failed cross-run resume",),
        ),
        _det(
            "durable-resume-completed",
            "Durable V3 completed replay makes zero provider calls",
            "DURABLE_V3_RESUME",
            "DURABLE_COMPLETED_REPLAY",
            "REGRESSION_EVAL",
            ("completed mission replay has zero provider calls",),
            ("provider_calls_zero",),
            critical=True,
            refs=("Durable V3 completed replay proof",),
        ),
        _det(
            "claim-fencing-storm",
            "Claim fencing and outbox suppress continuation storm",
            "CLAIM_FENCING",
            "CLAIM_FENCING",
            "REGRESSION_EVAL",
            ("settled attempt has no active claim", "cancelled-run continuation suppressed"),
            ("no_active_claim", "cancelled_continuation_zero"),
            critical=True,
            refs=("claim fencing continuation storm incident",),
        ),
        _det(
            "agent-office-isolated-mutation",
            "Agent Office mutating worker executes in isolated workspace",
            "AGENT_OFFICE",
            "AGENT_OFFICE_ISOLATION",
            "REGRESSION_EVAL",
            ("mutation isolated", "canonical push authority none"),
            ("isolated_workspace", "canonical_push_none"),
            critical=True,
            refs=("tests/test_block_a_agent_execution_foundation.py",),
        ),
        _det(
            "agent-office-result-envelope",
            "Agent Office result artifact is content-addressed and reducer verified",
            "AGENT_OFFICE",
            "TASK_RESULT_INTEGRITY",
            "REGRESSION_EVAL",
            ("TaskResultEnvelope integrity valid", "Harness reducer accepts evidence"),
            ("result_hash_valid", "harness_reduction_valid"),
            critical=True,
            refs=("app/services/task_result_envelope_service.py",),
        ),
        _det(
            "task-protocol-atomicity",
            "Task protocol rejects compound non-atomic worker goal",
            "TASK_PROTOCOL",
            "TASK_ATOMICITY",
            "CAPABILITY_EVAL",
            ("compound goal rejected or decomposed before worker selection",),
            ("atomicity_gate",),
            refs=("app/services/task_atomicity_service.py",),
        ),
        _det(
            "task-protocol-dependency",
            "Task dependency preconditions block premature execution",
            "TASK_PROTOCOL",
            "TASK_DEPENDENCY_PRECONDITION",
            "REGRESSION_EVAL",
            ("task blocked until direct dependency result is valid",),
            ("dependency_precondition_enforced",),
            critical=True,
            refs=("app/services/task_dependency_precondition_service.py",),
        ),
        _model(
            "editorial-evidence-gap",
            "Editorial evidence expansion reaches supported duration without padding",
            "EDITORIAL_EVIDENCE_GAP",
            "EDITORIAL_EVIDENCE_SYNTHESIS",
            "CAPABILITY_EVAL",
            ("supported editorial duration meets target", "unsupported claims zero", "artificial padding off"),
            "Human-calibrated grader checks evidence-grounded coherence and absence of repetitive padding.",
            refs=("editorial evidence gap incident",),
        ),
        _model(
            "gta6-fact-check-official",
            "GTA6 claim synthesis distinguishes official evidence from rumor",
            "GTA6_FACT_CHECK",
            "GTA6_FACT_CHECK",
            "CAPABILITY_EVAL",
            ("official/primary claims separated from rumor/unverified claims",),
            "Human-calibrated grader checks factual attribution, uncertainty handling, and no rumor-to-fact promotion.",
            refs=("GTA6 fact-check history",),
        ),
        _model(
            "gta6-source-conflict",
            "GTA6 conflicting-source review explains evidence strength without unsupported certainty",
            "GTA6_FACT_CHECK",
            "GTA6_SOURCE_CONFLICT",
            "CAPABILITY_EVAL",
            ("source conflict identified", "confidence reflects evidence"),
            "Human-calibrated grader checks whether conflicting evidence is synthesized accurately and usefully.",
            refs=("GTA6 editorial evidence map",),
        ),
        _det(
            "youtube-capability-route",
            "YouTube delivery requirement resolves to YouTube/Telegram review capability rather than analytics",
            "YOUTUBE_CAPABILITY_ROUTING",
            "YOUTUBE_DELIVERY_ROUTING",
            "REGRESSION_EVAL",
            ("delivery capability selected", "analytics capability not substituted"),
            ("typed_requirement_bound", "resolver_capability_match"),
            critical=True,
            refs=("YouTube capability routing mismatch incident",),
        ),
        _det(
            "youtube-private-only",
            "YouTube review upload remains PRIVATE until explicit human publication order",
            "YOUTUBE_CAPABILITY_ROUTING",
            "YOUTUBE_PRIVACY_GATE",
            "REGRESSION_EVAL",
            ("privacy_status=private", "public/unlisted publication absent"),
            ("private_status", "no_publication_escalation"),
            critical=True,
            refs=("YouTube PRIVATE review policy",),
        ),
        _det(
            "media-qa-final-master",
            "Final master satisfies deterministic media QA gates",
            "MEDIA_QA",
            "MEDIA_QA",
            "REGRESSION_EVAL",
            ("1080p", "30fps", "H264", "AAC", "duration>=20m", "overlay_leakage=0"),
            ("resolution", "fps", "video_codec", "audio_codec", "duration_gate", "overlay_gate"),
            critical=True,
            refs=("MASTER_FINAL QA gates",),
        ),
    ]
    return AgentTaskEvalSuite.create(
        suite_id="agent-task-foundation-history-v1",
        cases=cases,
        created_at="2026-09-30T00:00:00+00:00",
    )


__all__ = [
    "AgentTaskEvalCase",
    "AgentTaskEvalSuite",
    "AgentTaskTrial",
    "AgentTaskTrialGrade",
    "build_foundation_eval_suite",
    "grade_trial",
]
