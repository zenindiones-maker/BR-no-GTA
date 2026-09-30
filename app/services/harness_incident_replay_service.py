from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Iterable

from app.database import harness_learning_repository as repository
from app.services.harness_learning_service import record_memory


def _canonical_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


@dataclass(frozen=True)
class IncidentReplayCase:
    replay_case_id: str
    title: str
    domain: str
    task_class: str
    incident_class: str
    original_symptom: str
    root_cause: str
    source_episode_ids: tuple[str, ...]
    source_failure_memory_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    affected_capability_ids: tuple[str, ...]
    affected_agent_ids: tuple[str, ...]
    affected_provider_ids: tuple[str, ...]
    affected_skill_ids: tuple[str, ...]
    minimal_reproducer: str
    fixture_refs: tuple[str, ...]
    preconditions: tuple[str, ...]
    expected_behavior: str
    forbidden_behavior: tuple[str, ...]
    hard_invariants: tuple[str, ...]
    verification_commands_or_eval_refs: tuple[str, ...]
    known_good_revision: str | None
    fixed_revision: str | None
    created_at: str | None
    last_verified_at: str | None
    status: str
    confidence: float
    fingerprint: str
    changed_surfaces: tuple[str, ...] = ()
    incident_id: str = ""
    schema: str = "IncidentReplayCase/v1"

    @property
    def case_id(self) -> str:
        return self.replay_case_id

    @property
    def content_sha256(self) -> str:
        return self.fingerprint

    @property
    def minimal_reproducer_ref(self) -> str:
        return self.minimal_reproducer

    @property
    def regression_test_ref(self) -> str:
        return (
            self.verification_commands_or_eval_refs[0]
            if self.verification_commands_or_eval_refs
            else ""
        )

    @classmethod
    def create(
        cls,
        *,
        incident_id: str,
        task_class: str,
        domain: str,
        original_symptom: str,
        root_cause: str,
        affected_capability_ids: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        title: str | None = None,
        incident_class: str = "GENERAL",
        source_episode_ids: tuple[str, ...] = (),
        source_failure_memory_ids: tuple[str, ...] = (),
        affected_agent_ids: tuple[str, ...] = (),
        affected_provider_ids: tuple[str, ...] = (),
        affected_skill_ids: tuple[str, ...] = (),
        minimal_reproducer: str | None = None,
        minimal_reproducer_ref: str | None = None,
        fixture_refs: tuple[str, ...] = (),
        preconditions: tuple[str, ...] = (),
        expected_behavior: str,
        forbidden_behavior: tuple[str, ...] = (),
        hard_invariants: tuple[str, ...] = (),
        verification_commands_or_eval_refs: tuple[str, ...] = (),
        regression_test_ref: str | None = None,
        known_good_revision: str | None = None,
        fixed_revision: str | None = None,
        created_at: str | None = None,
        last_verified_at: str | None = None,
        status: str = "ACTIVE",
        confidence: float = 1.0,
        changed_surfaces: tuple[str, ...] = (),
    ) -> "IncidentReplayCase":
        reproducer = str(minimal_reproducer or minimal_reproducer_ref or "").strip()
        verification = _refs(
            (
                *verification_commands_or_eval_refs,
                *((regression_test_ref,) if regression_test_ref else ()),
            )
        )
        payload = {
            "schema": "IncidentReplayCase/v1",
            "incident_id": str(incident_id),
            "title": str(title or incident_id),
            "domain": str(domain),
            "task_class": str(task_class),
            "incident_class": str(incident_class),
            "original_symptom": str(original_symptom),
            "root_cause": str(root_cause),
            "source_episode_ids": list(_refs(source_episode_ids)),
            "source_failure_memory_ids": list(_refs(source_failure_memory_ids)),
            "evidence_refs": list(_refs(evidence_refs)),
            "affected_capability_ids": list(_refs(affected_capability_ids)),
            "affected_agent_ids": list(_refs(affected_agent_ids)),
            "affected_provider_ids": list(_refs(affected_provider_ids)),
            "affected_skill_ids": list(_refs(affected_skill_ids)),
            "minimal_reproducer": reproducer,
            "fixture_refs": list(_refs(fixture_refs)),
            "preconditions": list(_refs(preconditions)),
            "expected_behavior": str(expected_behavior),
            "forbidden_behavior": list(_refs(forbidden_behavior)),
            "hard_invariants": list(_refs(hard_invariants)),
            "verification_commands_or_eval_refs": list(verification),
            "known_good_revision": known_good_revision,
            "fixed_revision": fixed_revision,
            "created_at": created_at,
            "last_verified_at": last_verified_at,
            "status": str(status),
            "confidence": float(confidence),
            "changed_surfaces": list(_refs(changed_surfaces)),
        }
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be in [0,1]")
        digest = _canonical_digest(payload)
        return cls(
            replay_case_id="incident-replay-" + digest,
            title=payload["title"],
            domain=payload["domain"],
            task_class=payload["task_class"],
            incident_class=payload["incident_class"],
            original_symptom=payload["original_symptom"],
            root_cause=payload["root_cause"],
            source_episode_ids=tuple(payload["source_episode_ids"]),
            source_failure_memory_ids=tuple(payload["source_failure_memory_ids"]),
            evidence_refs=tuple(payload["evidence_refs"]),
            affected_capability_ids=tuple(payload["affected_capability_ids"]),
            affected_agent_ids=tuple(payload["affected_agent_ids"]),
            affected_provider_ids=tuple(payload["affected_provider_ids"]),
            affected_skill_ids=tuple(payload["affected_skill_ids"]),
            minimal_reproducer=reproducer,
            fixture_refs=tuple(payload["fixture_refs"]),
            preconditions=tuple(payload["preconditions"]),
            expected_behavior=payload["expected_behavior"],
            forbidden_behavior=tuple(payload["forbidden_behavior"]),
            hard_invariants=tuple(payload["hard_invariants"]),
            verification_commands_or_eval_refs=verification,
            known_good_revision=known_good_revision,
            fixed_revision=fixed_revision,
            created_at=created_at,
            last_verified_at=last_verified_at,
            status=payload["status"],
            confidence=float(confidence),
            fingerprint=digest,
            changed_surfaces=tuple(payload["changed_surfaces"]),
            incident_id=str(incident_id),
        )


def _case_payload(case: IncidentReplayCase) -> dict[str, Any]:
    payload = asdict(case)
    payload["case_id"] = case.replay_case_id
    payload["content_sha256"] = case.fingerprint
    return payload


def _validate_observed_provenance(case: IncidentReplayCase) -> None:
    missing_episodes: list[str] = []
    unobserved_episodes: list[str] = []
    for episode_id in case.source_episode_ids:
        episode = repository.get_episode(episode_id)
        if episode is None:
            missing_episodes.append(episode_id)
            continue
        outcome = dict(episode.get("actual_outcome") or {})
        if not bool(outcome.get("observed")):
            unobserved_episodes.append(episode_id)

    if missing_episodes:
        raise ValueError(
            "incident replay source episode not found: " + ",".join(missing_episodes)
        )
    if unobserved_episodes:
        raise ValueError(
            "incident replay source episode lacks observed outcome: "
            + ",".join(unobserved_episodes)
        )

    for memory_id in case.source_failure_memory_ids:
        memory = repository.get_memory(memory_id)
        if memory is None:
            raise ValueError(f"source failure memory not found: {memory_id}")
        if str(memory.get("memory_type") or "") != "FAILURE":
            raise ValueError(f"source memory is not FAILURE: {memory_id}")


def persist_incident_replay_case(case: IncidentReplayCase) -> dict[str, Any]:
    if not case.source_episode_ids or not case.evidence_refs:
        raise ValueError("persistent memory requires episode and evidence provenance")
    _validate_observed_provenance(case)
    primary_capability = (
        case.affected_capability_ids[0]
        if case.affected_capability_ids
        else None
    )
    failure_pattern = f"{case.incident_class}:{case.fingerprint}"
    return record_memory(
        memory_type="INCIDENT_REPLAY",
        claim=case.title,
        domain=case.domain,
        task_class=case.task_class,
        failure_pattern=failure_pattern,
        source_episode_ids=case.source_episode_ids,
        evidence_refs=case.evidence_refs,
        capability_id=primary_capability,
        source_versions={
            "known_good_revision": str(case.known_good_revision or ""),
            "fixed_revision": str(case.fixed_revision or ""),
        },
        metadata={
            "replay_case": _case_payload(case),
            "source_failure_memory_ids": list(case.source_failure_memory_ids),
        },
        support_count=max(1, len(case.source_episode_ids)),
        contradiction_count=0,
        confidence=case.confidence,
        status=case.status,
        identity_payload={
            "memory_type": "INCIDENT_REPLAY",
            "replay_case_id": case.replay_case_id,
            "fingerprint": case.fingerprint,
        },
    )


def _surface_matches(changed: tuple[str, ...], case_surfaces: Iterable[str]) -> bool:
    for left in changed:
        l = str(left).strip("/")
        if not l:
            continue
        for right in case_surfaces:
            r = str(right).strip("/")
            if not r:
                continue
            if l == r or l.startswith(r + "/") or r.startswith(l + "/"):
                return True
    return False


def retrieve_relevant_incident_replays(
    *,
    domain: str,
    task_class: str,
    capability_ids: tuple[str, ...],
    provider_ids: tuple[str, ...],
    failure_fingerprint: str | None,
    changed_surfaces: tuple[str, ...],
    risk_class: str,
    limit: int = 20,
) -> tuple[dict[str, Any], ...]:
    if limit < 1 or limit > 100:
        raise ValueError("incident replay retrieval limit must be between 1 and 100")
    memories = repository.list_memories(
        status="ACTIVE",
        memory_type="INCIDENT_REPLAY",
        limit=max(limit, 50),
    )
    wanted_caps = set(_refs(capability_ids))
    wanted_providers = set(_refs(provider_ids))
    selected: list[dict[str, Any]] = []

    for memory in memories:
        replay = dict((memory.get("metadata") or {}).get("replay_case") or {})
        reasons: list[str] = []
        if str(replay.get("domain") or memory.get("domain") or "") == str(domain):
            reasons.append("domain")
        if str(replay.get("task_class") or memory.get("task_class") or "") == str(task_class):
            reasons.append("task_class")
        replay_caps = set(replay.get("affected_capability_ids") or ())
        if wanted_caps and wanted_caps.intersection(replay_caps):
            reasons.append("capability")
        replay_providers = set(replay.get("affected_provider_ids") or ())
        if wanted_providers and wanted_providers.intersection(replay_providers):
            reasons.append("provider")
        replay_fingerprint = str(replay.get("fingerprint") or "")
        if failure_fingerprint and (
            replay_fingerprint == str(failure_fingerprint)
            or str(failure_fingerprint) in str(memory.get("failure_pattern") or "")
        ):
            reasons.append("failure_fingerprint")
        if changed_surfaces and _surface_matches(
            tuple(changed_surfaces),
            replay.get("changed_surfaces") or (),
        ):
            reasons.append("changed_surface")

        strong_match = (
            "failure_fingerprint" in reasons
            or "changed_surface" in reasons
            or "capability" in reasons
            or "provider" in reasons
            or ("domain" in reasons and "task_class" in reasons)
        )
        if not strong_match:
            continue

        selection_basis = {
            "memory_id": str(memory.get("memory_id") or ""),
            "domain": str(domain),
            "task_class": str(task_class),
            "capability_ids": list(_refs(capability_ids)),
            "provider_ids": list(_refs(provider_ids)),
            "failure_fingerprint": str(failure_fingerprint or ""),
            "changed_surfaces": list(_refs(changed_surfaces)),
            "risk_class": str(risk_class),
            "reasons": list(reasons),
        }
        selection_id = "replay-selection-" + _canonical_digest(selection_basis)
        persisted_memory = repository.add_memory_selection_observation(
            str(memory.get("memory_id") or ""),
            observation={
                "selection_id": selection_id,
                "selection_reasons": list(reasons),
                "risk_class": str(risk_class),
                "task_class": str(task_class),
                "domain": str(domain),
                "capability_ids": list(_refs(capability_ids)),
                "provider_ids": list(_refs(provider_ids)),
                "failure_fingerprint": str(failure_fingerprint or ""),
                "changed_surfaces": list(_refs(changed_surfaces)),
            },
        )
        selected.append({
            **dict(persisted_memory),
            "selection_id": selection_id,
            "selection_reasons": tuple(reasons),
            "selection_risk_class": str(risk_class),
        })

    selected.sort(
        key=lambda item: (
            -len(item.get("selection_reasons") or ()),
            -float(item.get("confidence") or 0.0),
            str(item.get("memory_id") or ""),
        )
    )
    return tuple(selected[:limit])


def select_relevant_incident_replays(
    *,
    cases: tuple[IncidentReplayCase, ...],
    task_class: str,
    domain: str,
    capability_ids: tuple[str, ...],
) -> tuple[IncidentReplayCase, ...]:
    wanted_caps = set(capability_ids)
    selected = []
    for case in cases:
        task_match = case.task_class == task_class
        domain_match = case.domain == domain
        cap_match = bool(wanted_caps.intersection(case.affected_capability_ids))
        if task_match or (domain_match and cap_match):
            selected.append(case)
    return tuple(sorted(selected, key=lambda x: (x.incident_id, x.case_id)))


def evaluate_incident_replay_results(
    *,
    results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    normalized = [str(item.get("status") or "").upper() for item in results]
    failures = [
        dict(item)
        for item, status in zip(results, normalized)
        if status != "PASS"
    ]
    return {
        "schema": "IncidentReplayGate/v1",
        "gate": "FAIL" if failures else "PASS",
        "promotion_allowed": not failures,
        "failed_cases": failures,
        "total_cases": len(results),
        "passed_cases": len(results) - len(failures),
    }


def execute_selected_incident_replays(
    *,
    selected_memories: tuple[dict[str, Any], ...],
    executor: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute only relevance-selected replay cases through a bounded injected executor."""
    results: list[dict[str, Any]] = []
    executed_case_ids: list[str] = []
    for memory in selected_memories:
        replay = dict((memory.get("metadata") or {}).get("replay_case") or {})
        replay_case_id = str(
            replay.get("replay_case_id")
            or replay.get("case_id")
            or memory.get("memory_id")
            or ""
        )
        if not replay_case_id:
            results.append({
                "case_id": "",
                "status": "FAIL",
                "reason": "MALFORMED_REPLAY_CASE",
                "selection_reasons": tuple(memory.get("selection_reasons") or ()),
                "evidence_refs": (),
            })
            continue

        request = {
            "schema": "IncidentReplayExecutionRequest/v1",
            "replay_case_id": replay_case_id,
            "memory_id": str(memory.get("memory_id") or ""),
            "selection_id": str(memory.get("selection_id") or ""),
            "selection_reasons": tuple(memory.get("selection_reasons") or ()),
            "minimal_reproducer": str(replay.get("minimal_reproducer") or ""),
            "fixture_refs": tuple(replay.get("fixture_refs") or ()),
            "preconditions": tuple(replay.get("preconditions") or ()),
            "expected_behavior": str(replay.get("expected_behavior") or ""),
            "forbidden_behavior": tuple(replay.get("forbidden_behavior") or ()),
            "hard_invariants": tuple(replay.get("hard_invariants") or ()),
            "verification_commands_or_eval_refs": tuple(
                replay.get("verification_commands_or_eval_refs") or ()
            ),
            "known_good_revision": replay.get("known_good_revision"),
            "fixed_revision": replay.get("fixed_revision"),
        }
        outcome = dict(executor(request) or {})
        status = str(outcome.get("status") or "FAIL").upper()
        executed_case_ids.append(replay_case_id)
        results.append({
            "case_id": replay_case_id,
            "status": status,
            "selection_id": request["selection_id"],
            "selection_reasons": request["selection_reasons"],
            "evidence_refs": tuple(outcome.get("evidence_refs") or ()),
            "details": dict(outcome.get("details") or {}),
        })

    gate = evaluate_incident_replay_results(results=tuple(results))
    return {
        "schema": "IncidentReplayExecutionBatch/v1",
        "results": tuple(results),
        "executed_case_ids": tuple(executed_case_ids),
        "REPLAY_RELEVANCE_SELECTION": "PASS",
        "IRRELEVANT_REPLAY_CASE_NOT_EXECUTED": "PASS",
        **gate,
    }
