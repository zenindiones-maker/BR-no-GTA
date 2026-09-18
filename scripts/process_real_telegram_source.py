from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.main import initialize_application
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    list_recent_telegram_user_inputs,
    update_telegram_source_state,
)
from app.services.telegram_fresh_research_service import (
    research_fresh_gta6_under_harness,
)
from app.services.telegram_learning_service import extract_source_url
from app.services.telegram_source_intelligence_service import (
    process_telegram_source_intelligence,
)


def _select_input(input_id: int | None) -> dict[str, Any]:
    if input_id is not None:
        record = get_telegram_user_input(input_id)
        if record is None:
            raise ValueError(f"Telegram input {input_id} not found")
        return record
    for record in list_recent_telegram_user_inputs(limit=200):
        if str(record.get("classification") or "").lower() != "news":
            continue
        if record.get("source_url") or extract_source_url(str(record.get("text_content") or "")):
            return record
    raise ValueError("no persisted Telegram news/URL input was found")


def _normalize_legacy_source(record: dict[str, Any]) -> dict[str, Any]:
    source_url = str(record.get("source_url") or "").strip()
    if not source_url:
        source_url = str(extract_source_url(str(record.get("text_content") or "")) or "").strip()
    if not source_url:
        raise ValueError("selected Telegram news input contains no resolvable HTTPS URL")
    if str(record.get("source_state") or ""):
        return record
    return update_telegram_source_state(
        int(record["id"]),
        source_state="SOURCE_CANDIDATE",
        source_url=source_url,
        learning_status="captured",
    )


def _proof(result: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    signal = result.get("editorial_signal")
    candidate = result.get("source_candidate")
    claims = result.get("claims") or []
    proof = {
        key: result.get(key)
        for key in (
            "REAL_TELEGRAM_SOURCE_INPUT",
            "SOURCE_CONTENT_RESOLVED",
            "FRESH_RESEARCH_TRIGGERED",
            "CLAIMS_EXTRACTED",
            "FACT_CHECK_EXECUTED",
            "SOURCE_HIERARCHY_ENFORCED",
            "UNVERIFIED_CLAIM_NOT_PROMOTED",
            "SEMANTIC_MEMORY_PROMOTED",
            "EDITORIAL_SIGNAL_CREATED",
            "EDITORIAL_SIGNAL_USED",
            "HUMAN_INPUT_LINEAGE_PRESERVED",
            "PREMATURE_INGRESS_MEMORY_QUARANTINED",
        )
    }
    proof.update(
        telegram_input_id=record["id"],
        memory_event_id=record.get("memory_event_id"),
        source_url=record.get("source_url"),
        source_candidate_id=(
            candidate.get("candidate_id") if isinstance(candidate, dict) else None
        ),
        source_state=(
            candidate.get("source_state") if isinstance(candidate, dict) else None
        ),
        editorial_signal_id=(
            signal.get("signal_id") if isinstance(signal, dict) else None
        ),
        editorial_decision=(
            signal.get("harness_decision") if isinstance(signal, dict) else None
        ),
        editorial_routing_id=(
            signal.get("routing_id") if isinstance(signal, dict) else None
        ),
        editorial_authorization_id=(
            signal.get("authorization_id") if isinstance(signal, dict) else None
        ),
        verified_claim_ids=[
            item.get("claim_id")
            for item in claims
            if item.get("verification_status") == "VERIFIED"
        ],
        promoted_semantic_memory_ids=[
            item.get("semantic_memory_id")
            for item in claims
            if item.get("semantic_memory_id") is not None
        ],
    )
    return proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Process a persisted real Telegram news/URL input through mandatory fresh "
            "research, source resolution, claim extraction, fact-check and governed "
            "editorial signal creation."
        )
    )
    parser.add_argument("--input-id", type=int)
    args = parser.parse_args(argv)

    initialize_application()
    record = _normalize_legacy_source(_select_input(args.input_id))
    fresh = research_fresh_gta6_under_harness(
        str(record.get("text_content") or record.get("source_url") or ""),
        source_context=record,
    )
    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=fresh,
    )
    proof = _proof(result, record)
    proof["fresh_research_execution_id"] = fresh.execution_id
    proof["fresh_research_routing_id"] = fresh.routing_id
    proof["fresh_research_execution_ref"] = fresh.execution_ref
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))

    required = {
        "REAL_TELEGRAM_SOURCE_INPUT": "PASS",
        "SOURCE_CONTENT_RESOLVED": "PASS",
        "FRESH_RESEARCH_TRIGGERED": "PASS",
        "SOURCE_HIERARCHY_ENFORCED": "PASS",
        "UNVERIFIED_CLAIM_NOT_PROMOTED": "PASS",
        "EDITORIAL_SIGNAL_CREATED": "PASS",
        "HUMAN_INPUT_LINEAGE_PRESERVED": "PASS",
    }
    failed = {
        key: {"expected": expected, "observed": proof.get(key)}
        for key, expected in required.items()
        if proof.get(key) != expected
    }
    if failed:
        print(
            json.dumps(
                {"REAL_TELEGRAM_SOURCE_PROOF": "INCOMPLETE", "gates": failed},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3

    # Claims/fact-check are mandatory only when usable source content yielded a
    # GTA6 claim. A source with no extractable GTA6 assertion remains evidence,
    # but cannot fabricate a claim merely to satisfy the proof.
    if proof.get("CLAIMS_EXTRACTED") != "PASS" or proof.get("FACT_CHECK_EXECUTED") != "PASS":
        print("REAL_TELEGRAM_SOURCE_PROOF=INSUFFICIENT_EXTRACTABLE_CLAIMS", file=sys.stderr)
        return 4

    print("REAL_TELEGRAM_SOURCE_PROOF=PASS")
    print(f"TELEGRAM_INPUT_ID={proof['telegram_input_id']}")
    print(f"SOURCE_CANDIDATE_ID={proof['source_candidate_id']}")
    print(f"EDITORIAL_SIGNAL_ID={proof['editorial_signal_id']}")
    print(f"EDITORIAL_DECISION={proof['editorial_decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
