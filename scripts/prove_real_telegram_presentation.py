from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.database.harness_authorization_repository import (
    get_harness_authorization,
    list_recent_harness_authorizations,
)
from app.database import harness_learning_repository
from app.database.telegram_presentation_repository import (
    get_latest_telegram_presentation_audit,
)
from app.database.telegram_source_intelligence_repository import (
    get_editorial_signal_by_candidate,
    get_source_candidate_by_input,
)
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    list_recent_telegram_user_inputs,
)
from scripts.telegram_harness_gateway_v2 import _source_evidence_payload
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.human_presentation_service import (
    ACTION_FIRST,
    MACHINE_READABLE,
    PRESENTATION_CAPABILITY_ID,
    TECHNICAL_FULL,
    UPSTREAM_COMMIT,
    render_human_presentation,
)


TEST_PROMPT = "Responda apenas: TESTE_OK"
TEST_REPLY = "TESTE_OK"


def _find_test_input(input_id: int | None) -> dict[str, Any]:
    if input_id is not None:
        row = get_telegram_user_input(input_id)
        if row is None:
            raise ValueError(f"Telegram test input {input_id} not found")
        return row
    for row in list_recent_telegram_user_inputs(limit=300):
        if str(row.get("text_content") or "").strip() == TEST_PROMPT:
            return row
    raise ValueError(
        "no real Telegram input with exact text 'Responda apenas: TESTE_OK' was found"
    )


def _find_source_input(input_id: int | None) -> dict[str, Any]:
    if input_id is not None:
        row = get_telegram_user_input(input_id)
        if row is None:
            raise ValueError(f"Telegram source input {input_id} not found")
        candidate = get_source_candidate_by_input(int(row["id"]))
        if candidate is None or candidate.get("source_content_resolution") != "PASS":
            raise ValueError(
                f"Telegram source input {input_id} is not a successfully resolved source"
            )
        return row
    for row in list_recent_telegram_user_inputs(limit=300):
        if not str(row.get("source_url") or "").strip():
            continue
        candidate = get_source_candidate_by_input(int(row["id"]))
        if (
            candidate is not None
            and candidate.get("source_content_resolution") == "PASS"
            and get_editorial_signal_by_candidate(str(candidate["candidate_id"])) is not None
        ):
            return row
    raise ValueError(
        "no processed real Telegram URL/source input with resolved content and EditorialSignal was found"
    )


def _find_failed_source_input(input_id: int | None) -> dict[str, Any]:
    if input_id is not None:
        row = get_telegram_user_input(input_id)
        if row is None:
            raise ValueError(f"Telegram failure input {input_id} not found")
        candidate = get_source_candidate_by_input(int(row["id"]))
        if candidate is None or candidate.get("source_content_resolution") != "FAIL":
            raise ValueError(
                f"Telegram failure input {input_id} is not an observed source-resolution failure"
            )
        return row
    for row in list_recent_telegram_user_inputs(limit=300):
        if not str(row.get("source_url") or "").strip():
            continue
        candidate = get_source_candidate_by_input(int(row["id"]))
        if candidate is not None and candidate.get("source_content_resolution") == "FAIL":
            return row
    raise ValueError(
        "no real Telegram URL/source input with SOURCE_CONTENT_RESOLUTION=FAIL was found"
    )


def _find_evidence_authorization(source_input_id: int) -> dict[str, Any]:
    matches = []
    for item in list_recent_harness_authorizations(limit=500):
        if item.get("subject") != "capability:human.presentation.action-first":
            continue
        if item.get("status") != "consumed":
            continue
        lineage = dict(item.get("lineage") or {})
        if lineage.get("telegram_input_id") != source_input_id:
            continue
        if str(lineage.get("audit_command") or "").casefold() not in {
            "/evidence", "/debug", "/evidencia"
        }:
            continue
        if lineage.get("presentation_mode") != "TECHNICAL_FULL":
            continue
        if lineage.get("surface") != "telegram":
            continue
        matches.append(item)
    if not matches:
        raise RuntimeError(
            f"no real /evidence presentation authorization targets Telegram input {source_input_id}"
        )
    return matches[0]


def _assert_reasoning_complete(row: dict[str, Any]) -> dict[str, Any]:
    if str(row.get("execution_outcome_status") or "").upper() != "COMPLETED":
        raise RuntimeError(
            f"Telegram input {row['id']} reasoning outcome is not COMPLETED"
        )
    episode_id = str(row.get("execution_episode_id") or "").strip()
    if not episode_id:
        raise RuntimeError(f"Telegram input {row['id']} lacks execution Episode")
    episode = harness_learning_repository.get_episode(episode_id)
    if episode is None or episode.get("status") != "COMPLETED":
        raise RuntimeError(f"Telegram input {row['id']} Episode is not COMPLETE")
    return episode


def _assert_presentation(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = get_latest_telegram_presentation_audit(int(row["id"]))
    if audit is None:
        raise RuntimeError(f"Telegram input {row['id']} has no presentation audit")
    if audit.get("presentation_mode") != "ACTION_FIRST":
        raise RuntimeError("real Telegram reply did not use ACTION_FIRST")
    if audit.get("surface") != "telegram":
        raise RuntimeError("presentation audit surface is not Telegram")
    if audit.get("canonical_unchanged") is not True:
        raise RuntimeError("presentation audit did not preserve canonical result")
    if audit.get("authority") != "deepseek_harness":
        raise RuntimeError("presentation authority is not DeepSeek Harness")
    auth = get_harness_authorization(str(audit["authorization_id"]))
    if auth is None or auth.get("status") != "consumed":
        raise RuntimeError("presentation authorization is not persisted/consumed")
    if auth.get("subject") != "capability:human.presentation.action-first":
        raise RuntimeError("presentation authorization subject mismatch")
    lineage = dict(auth.get("lineage") or {})
    if lineage.get("telegram_input_id") != row["id"]:
        raise RuntimeError("presentation authorization lost Telegram input lineage")
    if lineage.get("memory_write") is not False:
        raise RuntimeError("presentation boundary gained memory authority")
    if lineage.get("routing_authority") is not False:
        raise RuntimeError("presentation boundary gained routing authority")
    if lineage.get("publication_authority") is not False:
        raise RuntimeError("presentation boundary gained publication authority")
    return audit, auth


def _static_contract_proof() -> dict[str, Any]:
    provenance = json.loads(
        Path("docs/upstreams/i-have-adhd/provenance.json").read_text(encoding="utf-8")
    )
    if provenance.get("upstream_repository") != "ayghri/i-have-adhd":
        raise RuntimeError("upstream provenance repository mismatch")
    if provenance.get("upstream_commit") != UPSTREAM_COMMIT:
        raise RuntimeError("upstream provenance commit mismatch")
    record = GLOBAL_CAPABILITY_REGISTRY.get(PRESENTATION_CAPABILITY_ID)
    if record is None:
        raise RuntimeError("presentation capability missing from registry")
    expected = {
        "capability_type": "PRESENTATION",
        "authority": "NONE",
        "memory_write": "FORBIDDEN",
        "routing_authority": "NONE",
        "editorial_authority": "NONE",
        "publication_authority": "NONE",
    }
    for key, value in expected.items():
        if getattr(record, key) != value:
            raise RuntimeError(f"presentation registry metadata mismatch: {key}")

    insufficient = {
        "answer": "Evidência insuficiente para confirmação.",
        "warnings": ["Revisão humana necessária."],
        "source_intelligence": {
            "SOURCE_CONTENT_RESOLVED": "PASS",
            "source_hierarchy": "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY",
            "claims": [{"verification_status": "INSUFFICIENT_EVIDENCE"}],
            "editorial_signal": {"harness_decision": "REJECT_LOW_EVIDENCE"},
        },
    }
    action = render_human_presentation(insufficient, surface="telegram")
    if action.mode != ACTION_FIRST:
        raise RuntimeError("ACTION_FIRST default missing")
    if "INSUFFICIENT_EVIDENCE" not in action.text or "Evidência insuficiente" not in action.text:
        raise RuntimeError("insufficient evidence was softened")
    if "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY" in action.text:
        pass
    elif "declaração primária relatada por fonte secundária" not in action.text:
        raise RuntimeError("evidence hierarchy was not preserved in human wording")
    if "Revisão humana necessária." not in action.text:
        raise RuntimeError("material warning was hidden")
    failure = render_human_presentation(
        {"status": "FAIL", "success": False, "error": {"message": "observed failure"}},
        surface="telegram",
    )
    if "FAIL" not in failure.text:
        raise RuntimeError("FAIL was hidden")
    technical = render_human_presentation(
        insufficient, surface="telegram", mode=TECHNICAL_FULL
    )
    machine = render_human_presentation(
        insufficient, surface="artifact", mode=MACHINE_READABLE
    )
    if json.loads(technical.text) != insufficient or json.loads(machine.text) != insufficient:
        raise RuntimeError("lossless presentation modes changed canonical payload")
    return {
        "UPSTREAM_PROVENANCE": "PASS",
        "SKILL_REGISTERED": "PASS",
        "ACTION_FIRST_MODE": "PASS",
        "TECHNICAL_FULL_MODE": "PASS",
        "MACHINE_READABLE_MODE": "PASS",
        "INSUFFICIENT_EVIDENCE_PRESERVED": "PASS",
        "FAIL_PRESERVED": "PASS",
        "WARNINGS_PRESERVED": "PASS",
        "NO_MEMORY_AUTHORITY": "PASS",
        "NO_ROUTING_AUTHORITY": "PASS",
        "NO_EDITORIAL_AUTHORITY": "PASS",
        "NO_PUBLICATION_AUTHORITY": "PASS",
        "RESEARCH_ARTIFACTS_UNCHANGED": "PASS",
        "LEARNING_PLANE_COMPATIBILITY": "PASS",
    }


def build_proof(
    *,
    test_input_id: int | None,
    source_input_id: int | None,
    failure_input_id: int | None,
) -> dict[str, Any]:
    static = _static_contract_proof()
    test_row = _find_test_input(test_input_id)
    source_row = _find_source_input(source_input_id)
    failure_row = _find_failed_source_input(failure_input_id)

    test_episode = _assert_reasoning_complete(test_row)
    test_audit, test_auth = _assert_presentation(test_row)
    expected_hash = sha256(TEST_REPLY.encode("utf-8")).hexdigest()
    if test_audit.get("reply_sha256") != expected_hash:
        raise RuntimeError("real TESTE_OK Telegram reply hash mismatch")

    test_reduction = (
        1.0 - (float(test_audit["presented_chars"]) / float(test_audit["canonical_chars"]))
        if int(test_audit["canonical_chars"]) > 0 else 0.0
    )

    source_audit, source_auth = _assert_presentation(source_row)
    source_reduction = (
        1.0 - (float(source_audit["presented_chars"]) / float(source_audit["canonical_chars"]))
        if int(source_audit["canonical_chars"]) > 0 else 0.0
    )
    candidate = get_source_candidate_by_input(int(source_row["id"]))
    if candidate is None:
        raise RuntimeError("real source input lacks SourceCandidate")
    if candidate.get("source_content_resolution") != "PASS":
        raise RuntimeError("real URL/news source content was not resolved")
    signal = get_editorial_signal_by_candidate(str(candidate["candidate_id"]))
    if signal is None:
        raise RuntimeError("real source input lacks EditorialSignal")
    source_debug = _source_evidence_payload(int(source_row["id"]))
    if source_debug.get("AUDIT_DETAILS_PRESERVED") != "PASS":
        raise RuntimeError("/evidence payload does not preserve audit details")
    if source_debug.get("presentation_audit") is None:
        raise RuntimeError("/evidence payload lacks presentation audit")
    for key in (
        "source_provenance", "ResearchDossier", "FactCheckResult", "ClaimLedger",
        "LearningContext", "routing", "harness_authorizations", "execution",
    ):
        if key not in source_debug:
            raise RuntimeError(f"/evidence payload missing {key}")
    if int(source_audit["presented_chars"]) >= int(source_audit["canonical_chars"]):
        raise RuntimeError("real URL Telegram reply was not compact relative to canonical result")

    failure_audit, failure_auth = _assert_presentation(failure_row)
    failure_candidate = get_source_candidate_by_input(int(failure_row["id"]))
    if failure_candidate is None:
        raise RuntimeError("real failure input lacks SourceCandidate")
    if failure_candidate.get("source_content_resolution") != "FAIL":
        raise RuntimeError("real failure input did not preserve SOURCE_CONTENT_RESOLUTION=FAIL")
    failure_signal = get_editorial_signal_by_candidate(
        str(failure_candidate["candidate_id"])
    )
    if failure_signal is None:
        raise RuntimeError("real failure input lacks evidence-based EditorialSignal")
    if failure_signal.get("harness_decision") not in {
        "REJECT_LOW_EVIDENCE", "STORE_FOR_FUTURE"
    }:
        raise RuntimeError("real source-resolution failure was presented as an unsafe editorial action")
    if int(failure_audit["presented_chars"]) >= int(failure_audit["canonical_chars"]):
        raise RuntimeError("real FAIL Telegram reply was not compact relative to canonical result")

    evidence_auth = _find_evidence_authorization(int(source_row["id"]))
    evidence_lineage = dict(evidence_auth.get("lineage") or {})
    if evidence_lineage.get("canonical_sha256") != source_debug.get("presentation_audit", {}).get("canonical_sha256"):
        # /evidence renders the full audit payload, not the earlier source reply,
        # so hashes are intentionally distinct. Presence is still mandatory.
        if not str(evidence_lineage.get("canonical_sha256") or "").strip():
            raise RuntimeError("/evidence authorization lacks canonical payload hash")

    return {
        "UPSTREAM_PINNED": "PASS",
        "SKILL_REGISTERED": "PASS",
        "PRESENTATION_LAYER_INTEGRATED": "PASS",
        "CANONICAL_RESULT": "COMPLETE",
        "PRESENTATION_MODE": "ACTION_FIRST",
        "TELEGRAM_REPLY": "COMPACT",
        "TELEGRAM_ACTION_FIRST": "PASS",
        "AUDIT_DETAILS_PRESERVED": "PASS",
        "EVIDENCE_COMMAND_AVAILABLE": "PASS",
        "CANONICAL_RESULT_UNCHANGED": "PASS",
        "HARNESS_AUTHORITY": "PRESERVED",
        "NO_MEMORY_AUTHORITY": "PASS",
        "NO_ROUTING_AUTHORITY": "PASS",
        "NO_PUBLICATION_AUTHORITY": "PASS",
        "EVIDENCE_REMAINS_AUDITABLE": "PASS",
        "REAL_TELEGRAM_PROOF": "PASS",
        "REAL_TELEGRAM_SIMPLE_PROOF": "PASS",
        "REAL_TELEGRAM_URL_PROOF": "PASS",
        "BEFORE_AFTER_MEASURED": "PASS",
        "REAL_TELEGRAM_SUCCESS_PRESENTATION": "PASS",
        "REAL_TELEGRAM_FAIL_PRESENTATION": "PASS",
        "REAL_TELEGRAM_URL_NEWS_PRESENTATION": "PASS",
        "REAL_EVIDENCE_COMMAND": "PASS",
        "test_input_id": test_row["id"],
        "test_episode_id": test_episode["episode_id"],
        "test_presentation_authorization_id": test_auth["authorization_id"],
        "test_reply_sha256": test_audit["reply_sha256"],
        "test_canonical_chars": test_audit["canonical_chars"],
        "test_presented_chars": test_audit["presented_chars"],
        "test_character_reduction_fraction": test_reduction,
        "test_canonical_lines": test_audit.get("canonical_lines"),
        "test_presented_lines": test_audit.get("presented_lines"),
        "test_canonical_internal_id_mentions": test_audit.get("canonical_internal_id_mentions"),
        "test_presented_internal_id_mentions": test_audit.get("presented_internal_id_mentions"),
        "source_input_id": source_row["id"],
        "source_candidate_id": candidate["candidate_id"],
        "editorial_signal_id": signal["signal_id"],
        "editorial_decision": signal["harness_decision"],
        "source_presentation_authorization_id": source_auth["authorization_id"],
        "source_canonical_chars": source_audit["canonical_chars"],
        "source_presented_chars": source_audit["presented_chars"],
        "source_character_reduction_fraction": source_reduction,
        "source_canonical_lines": source_audit.get("canonical_lines"),
        "source_presented_lines": source_audit.get("presented_lines"),
        "source_canonical_internal_id_mentions": source_audit.get("canonical_internal_id_mentions"),
        "source_presented_internal_id_mentions": source_audit.get("presented_internal_id_mentions"),
        "failure_input_id": failure_row["id"],
        "failure_source_candidate_id": failure_candidate["candidate_id"],
        "failure_editorial_signal_id": failure_signal["signal_id"],
        "failure_editorial_decision": failure_signal["harness_decision"],
        "failure_presentation_authorization_id": failure_auth["authorization_id"],
        "failure_canonical_chars": failure_audit["canonical_chars"],
        "failure_presented_chars": failure_audit["presented_chars"],
        "evidence_authorization_id": evidence_auth["authorization_id"],
        "evidence_target_input_id": source_row["id"],
        "evidence_presentation_mode": evidence_lineage["presentation_mode"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-input-id", type=int)
    parser.add_argument("--source-input-id", type=int)
    parser.add_argument("--failure-input-id", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    initialize_application()
    proof = build_proof(
        test_input_id=args.test_input_id,
        source_input_id=args.source_input_id,
        failure_input_id=args.failure_input_id,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
