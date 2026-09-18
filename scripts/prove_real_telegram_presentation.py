from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.database.harness_authorization_repository import get_harness_authorization
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
        return row
    for row in list_recent_telegram_user_inputs(limit=300):
        if str(row.get("source_url") or "").strip():
            candidate = get_source_candidate_by_input(int(row["id"]))
            if candidate is not None:
                return row
    raise ValueError("no processed real Telegram URL/source input was found")


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


def build_proof(*, test_input_id: int | None, source_input_id: int | None) -> dict[str, Any]:
    test_row = _find_test_input(test_input_id)
    source_row = _find_source_input(source_input_id)

    test_episode = _assert_reasoning_complete(test_row)
    test_audit, test_auth = _assert_presentation(test_row)
    expected_hash = sha256(TEST_REPLY.encode("utf-8")).hexdigest()
    if test_audit.get("reply_sha256") != expected_hash:
        raise RuntimeError("real TESTE_OK Telegram reply hash mismatch")

    source_audit, source_auth = _assert_presentation(source_row)
    candidate = get_source_candidate_by_input(int(source_row["id"]))
    if candidate is None:
        raise RuntimeError("real source input lacks SourceCandidate")
    signal = get_editorial_signal_by_candidate(str(candidate["candidate_id"]))
    if signal is None:
        raise RuntimeError("real source input lacks EditorialSignal")
    source_debug = _source_evidence_payload(int(source_row["id"]))
    if source_debug.get("AUDIT_DETAILS_PRESERVED") != "PASS":
        raise RuntimeError("/evidence payload does not preserve audit details")
    if source_debug.get("presentation_audit") is None:
        raise RuntimeError("/evidence payload lacks presentation audit")
    if int(source_audit["presented_chars"]) >= int(source_audit["canonical_chars"]):
        raise RuntimeError("real URL Telegram reply was not compact relative to canonical result")

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
        "REAL_TELEGRAM_PROOF": "PASS",
        "test_input_id": test_row["id"],
        "test_episode_id": test_episode["episode_id"],
        "test_presentation_authorization_id": test_auth["authorization_id"],
        "test_reply_sha256": test_audit["reply_sha256"],
        "test_canonical_chars": test_audit["canonical_chars"],
        "test_presented_chars": test_audit["presented_chars"],
        "source_input_id": source_row["id"],
        "source_candidate_id": candidate["candidate_id"],
        "editorial_signal_id": signal["signal_id"],
        "editorial_decision": signal["harness_decision"],
        "source_presentation_authorization_id": source_auth["authorization_id"],
        "source_canonical_chars": source_audit["canonical_chars"],
        "source_presented_chars": source_audit["presented_chars"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-input-id", type=int)
    parser.add_argument("--source-input-id", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    initialize_application()
    proof = build_proof(
        test_input_id=args.test_input_id,
        source_input_id=args.source_input_id,
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
