from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import unicodedata
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database.memory_claim_repository import get_memory_claim
from app.services.gta6_knowledge_retrieval_service import retrieve_gta6_knowledge


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold().strip()


def _evaluation_cases(limit: int = 20) -> list[dict[str, Any]]:
    lineage = continuous_repository.list_claim_lineage(limit=1000)
    metadata = {
        int(item["claim_id"]): item
        for item in brain_repository.list_claim_metadata(limit=2000)
    }
    by_subject: dict[str, dict[str, Any]] = {}
    for row in lineage:
        claim_id = int(row["claim_id"])
        claim = get_memory_claim(claim_id)
        if claim is None or str(claim.get("status") or "").casefold() != "active":
            continue
        meta = metadata.get(claim_id, {})
        if str(meta.get("brain_status") or "ACTIVE").upper() not in {
            "ACTIVE", "VERIFIED",
        }:
            continue
        subject = str(row.get("subject") or "").strip()
        if not subject:
            continue
        key = _fold(subject)
        case = by_subject.setdefault(key, {
            "query": subject,
            "subject": subject,
            "relevant_claim_ids": [],
            "official_relevant_claim_ids": [],
        })
        case["relevant_claim_ids"].append(claim_id)
        if str(row.get("source_type") or "").upper() in {
            "PRIMARY_SOURCE", "OFFICIAL",
        } or str(row.get("evidence_class") or "").upper() in {
            "PRIMARY_SOURCE", "OFFICIAL",
        }:
            case["official_relevant_claim_ids"].append(claim_id)
    cases = [
        item for item in by_subject.values()
        if item["relevant_claim_ids"]
    ]
    cases.sort(
        key=lambda item: (
            -len(item["official_relevant_claim_ids"]),
            -len(item["relevant_claim_ids"]),
            _fold(item["subject"]),
        )
    )
    return cases[:limit]


def _metrics(
    ordered: list[dict[str, Any]],
    relevant: set[int],
    *,
    k: int = 5,
) -> dict[str, float]:
    top = ordered[:k]
    ids = [int(item["claim_id"]) for item in top]
    hits = sum(1 for claim_id in ids if claim_id in relevant)
    return {
        "precision_at_k": round(hits / max(1, len(ids)), 6),
        "recall_at_k": round(hits / max(1, len(relevant)), 6),
    }


def _source_correctness(
    ordered: list[dict[str, Any]],
    official_relevant: set[int],
) -> float:
    if not official_relevant:
        return 1.0
    if not ordered:
        return 0.0
    return 1.0 if int(ordered[0]["claim_id"]) in official_relevant else 0.0


def run(output: Path) -> dict[str, Any]:
    cases = _evaluation_cases()
    evaluations: list[dict[str, Any]] = []
    started = time.perf_counter()

    for case in cases:
        call_started = time.perf_counter()
        retrieval = retrieve_gta6_knowledge(
            query=case["query"],
            limit=20,
            max_context_bytes=32 * 1024,
            include_history=False,
        )
        latency = time.perf_counter() - call_started
        units = list(retrieval.get("knowledge_units") or ())
        relevant = {int(item) for item in case["relevant_claim_ids"]}
        official_relevant = {
            int(item) for item in case["official_relevant_claim_ids"]
        }

        lexical = sorted(
            units,
            key=lambda item: (
                -float((item.get("scores") or {}).get("lexical") or 0.0),
                -float((item.get("scores") or {}).get("source_quality") or 0.0),
                -int(item["claim_id"]),
            ),
        )
        entity_graph = sorted(
            units,
            key=lambda item: (
                -float((item.get("scores") or {}).get("entity_graph") or 0.0),
                -float((item.get("scores") or {}).get("source_quality") or 0.0),
                -int(item["claim_id"]),
            ),
        )
        hybrid = units
        lexical_metrics = _metrics(lexical, relevant)
        entity_metrics = _metrics(entity_graph, relevant)
        hybrid_metrics = _metrics(hybrid, relevant)
        lexical_source = _source_correctness(lexical, official_relevant)
        graph_source = _source_correctness(entity_graph, official_relevant)
        hybrid_source = _source_correctness(hybrid, official_relevant)
        evaluations.append({
            **case,
            "candidate_count": retrieval.get("candidate_count"),
            "context_bytes": retrieval.get("context_bytes"),
            "bounded_context": retrieval.get("bounded_context"),
            "latency_seconds": latency,
            "lexical_only": {
                **lexical_metrics,
                "source_correctness": lexical_source,
                "claim_ids": [int(item["claim_id"]) for item in lexical[:5]],
            },
            "semantic_only": {
                "method": "ENTITY_GRAPH_ONLY_NO_EMBEDDINGS",
                **entity_metrics,
                "source_correctness": graph_source,
                "claim_ids": [int(item["claim_id"]) for item in entity_graph[:5]],
            },
            "hybrid": {
                **hybrid_metrics,
                "source_correctness": hybrid_source,
                "claim_ids": [int(item["claim_id"]) for item in hybrid[:5]],
            },
            "graph_expansion_useful": any(
                float((item.get("scores") or {}).get("entity_graph") or 0.0) > 0
                for item in hybrid
            ),
            "duplicate_suppression": (
                len({int(item["claim_id"]) for item in hybrid}) == len(hybrid)
            ),
            "temporal_correctness": all(
                str(item.get("brain_status") or "").upper()
                in {"", "ACTIVE", "VERIFIED"}
                and str(item.get("status") or "").casefold() == "active"
                for item in hybrid
            ),
        })

    def average(path: tuple[str, str]) -> float:
        values = [
            float(item[path[0]][path[1]])
            for item in evaluations
        ]
        return round(sum(values) / max(1, len(values)), 6)

    lexical = {
        "precision_at_k": average(("lexical_only", "precision_at_k")),
        "recall_at_k": average(("lexical_only", "recall_at_k")),
        "source_correctness": average(("lexical_only", "source_correctness")),
    }
    semantic = {
        "method": "ENTITY_GRAPH_ONLY_NO_EMBEDDINGS",
        "precision_at_k": average(("semantic_only", "precision_at_k")),
        "recall_at_k": average(("semantic_only", "recall_at_k")),
        "source_correctness": average(("semantic_only", "source_correctness")),
        "embedding_semantic_status": "NOT_PROMOTED",
    }
    hybrid = {
        "precision_at_k": average(("hybrid", "precision_at_k")),
        "recall_at_k": average(("hybrid", "recall_at_k")),
        "source_correctness": average(("hybrid", "source_correctness")),
    }
    hybrid_promoted = bool(
        evaluations
        and hybrid["precision_at_k"] >= lexical["precision_at_k"]
        and hybrid["recall_at_k"] >= lexical["recall_at_k"]
        and hybrid["source_correctness"] >= lexical["source_correctness"]
        and all(item["bounded_context"] for item in evaluations)
        and all(item["duplicate_suppression"] for item in evaluations)
        and all(item["temporal_correctness"] for item in evaluations)
    )
    report = {
        "schema": "gta6-retrieval-benchmark/v1",
        "status": "PASS" if evaluations else "INSUFFICIENT_REAL_KNOWLEDGE",
        "real_canonical_cases": len(evaluations),
        "lexical_only": lexical,
        "semantic_only": semantic,
        "hybrid": hybrid,
        "HYBRID_RETRIEVAL": "PASS" if hybrid_promoted else "NOT_PROMOTED",
        "bounded_context_max_bytes": max(
            [int(item["context_bytes"] or 0) for item in evaluations] or [0]
        ),
        "mean_latency_seconds": round(
            sum(float(item["latency_seconds"]) for item in evaluations)
            / max(1, len(evaluations)),
            6,
        ),
        "duplicate_suppression": all(
            item["duplicate_suppression"] for item in evaluations
        ),
        "temporal_correctness": all(
            item["temporal_correctness"] for item in evaluations
        ),
        "graph_expansion_useful_cases": sum(
            1 for item in evaluations if item["graph_expansion_useful"]
        ),
        "evaluations": evaluations,
        "elapsed_seconds": time.perf_counter() - started,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print("RETRIEVAL_REAL_CASES=" + str(report["real_canonical_cases"]))
    print("LEXICAL_PRECISION_AT_K=" + str(lexical["precision_at_k"]))
    print("LEXICAL_RECALL_AT_K=" + str(lexical["recall_at_k"]))
    print("SEMANTIC_ONLY_METHOD=" + str(semantic["method"]))
    print("SEMANTIC_EMBEDDINGS=NOT_PROMOTED")
    print("HYBRID_PRECISION_AT_K=" + str(hybrid["precision_at_k"]))
    print("HYBRID_RECALL_AT_K=" + str(hybrid["recall_at_k"]))
    print("HYBRID_RETRIEVAL=" + report["HYBRID_RETRIEVAL"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/gta6-knowledge-brain/retrieval-benchmark.json",
    )
    args = parser.parse_args()
    report = run(Path(args.output))
    return 0 if report["status"] in {"PASS", "INSUFFICIENT_REAL_KNOWLEDGE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
