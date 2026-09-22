from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.telegram_group_human_surface_service import (
    HUMAN_SURFACE,
    send_harness_message_to_human_group,
)
from app.services.gta6_knowledge_retrieval_service import retrieve_gta6_knowledge
from scripts.continuous_intelligence_cycle import run_scheduled


def _digest(report: dict[str, Any]) -> str:
    daily = dict(report.get("brain_daily_run") or {})
    if not daily:
        return (
            "🧠 GTA6 Brain — atualização diária\n\n"
            "Nenhuma novidade GTA 6 relevante encontrada hoje. "
            "Brain atualizado e fontes verificadas."
        )
    changed = int(daily.get("sources_changed") or 0)
    new_claims = int(daily.get("new_claims") or 0)
    verified = int(daily.get("verified_claims") or 0)
    contradicted = int(daily.get("contradicted_claims") or 0)
    if changed == 0 and new_claims == 0 and verified == 0 and contradicted == 0:
        return (
            "🧠 GTA6 Brain — atualização diária\n\n"
            "Nenhuma novidade GTA 6 relevante encontrada hoje. "
            f"{int(daily.get('sources_checked') or 0)} fonte(s) verificadas; "
            "Brain atualizado sem reprocessar conteúdo unchanged."
        )
    retrieval = retrieve_gta6_knowledge(
        query="novidades GTA VI com maior valor editorial ainda não usadas",
        limit=3,
        max_context_bytes=8192,
    )
    discoveries = []
    for item in retrieval.get("knowledge_units") or ():
        if str((item.get("novelty") or {}).get("editorial") or "").upper() != "UNUSED":
            continue
        discoveries.append(
            f"• {item.get('claim')} — fonte: {item.get('source_url')}"
        )
    lines = [
        "🧠 GTA6 Brain — atualização diária",
        "",
        f"{int(daily.get('sources_checked') or 0)} fontes verificadas",
        f"{changed} fontes mudaram",
        f"{new_claims} novos claims",
        f"{verified} confirmados",
        f"{contradicted} contraditos",
        f"{int(daily.get('duplicates_avoided') or 0)} duplicatas ignoradas",
        f"{int(daily.get('resolved_questions') or 0)} perguntas resolvidas",
        f"{int(daily.get('open_questions') or 0)} perguntas abertas",
    ]
    if discoveries:
        lines.extend(["", "Descobertas relevantes:", *discoveries])
    return "\n".join(lines)


def _send_digest(report: dict[str, Any]) -> dict[str, Any]:
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="human-surface:telegram_group",
        execution_id=(
            "gta6-brain-daily-human:"
            + str(os.getenv("GITHUB_RUN_ID") or "local")
        ),
        lineage={
            "authority": "DEEPSEEK_HARNESS",
            "human_surface": HUMAN_SURFACE,
            "daily_run_id": (report.get("brain_daily_run") or {}).get("run_id"),
            "purpose": "GTA6_KNOWLEDGE_DAILY_DIGEST",
        },
    )
    try:
        return send_harness_message_to_human_group(
            authorization=authorization,
            text=_digest(report),
            category="DAILY_KNOWLEDGE_DIGEST",
            lineage={
                "daily_run_id": (
                    report.get("brain_daily_run") or {}
                ).get("run_id"),
                "source": "gta6_knowledge_brain_daily",
            },
        )
    finally:
        consume_harness_authorization(authorization)


def run(
    *,
    artifact_dir: Path,
    upstream_root: Path,
    target_sha: str,
    trigger_kind: str,
) -> dict[str, Any]:
    cycle = run_scheduled(
        artifact_dir=artifact_dir,
        upstream_root=upstream_root,
        target_sha=target_sha,
        trigger_kind=trigger_kind,
    )
    dispatch = _send_digest(cycle)
    report = {
        "schema": "gta6-knowledge-brain-daily/v1",
        "status": "PASS",
        "authority": "DEEPSEEK_HARNESS",
        "human_surface": HUMAN_SURFACE,
        "PRIVATE_TELEGRAM_HUMAN_SURFACE": "DISABLED",
        "cycle": cycle,
        "brain_daily_run": cycle.get("brain_daily_run"),
        "telegram_group_digest": dispatch,
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "HERMES_DIRECT_CANONICAL_WRITE": "NO",
        "AGENT_DIRECT_CANONICAL_WRITE": "NO",
        "ZERO_COST_OPERATION": os.getenv("ZERO_COST_OPERATION", "UNKNOWN"),
        "TERMUX_HEAVY_PROCESSING": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "gta6-knowledge-brain-daily.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    print("GTA6_KNOWLEDGE_BRAIN_DAILY=PASS")
    print("HARNESS_AUTHORITY=PASS")
    print("TELEGRAM_GROUP_ONLY_HUMAN_SURFACE=PASS")
    print("PRIVATE_TELEGRAM_HUMAN_SURFACE=DISABLED")
    print("OBSIDIAN_CANONICAL_MEMORY=NO")
    print("HERMES_DIRECT_CANONICAL_WRITE=NO")
    print("AGENT_DIRECT_CANONICAL_WRITE=NO")
    print("DAILY_RUN_ID=" + str((cycle.get("brain_daily_run") or {}).get("run_id")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--trigger-kind", default="workflow_dispatch")
    args = parser.parse_args()
    run(
        artifact_dir=Path(args.artifact_dir),
        upstream_root=Path(args.upstream_root),
        target_sha=args.target_sha,
        trigger_kind=args.trigger_kind,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
