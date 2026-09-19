from __future__ import annotations

import argparse
import ast
import compileall
import inspect
import json
from pathlib import Path
import time
from typing import Any

from app.database.schema import initialize_schema
from app.services.ai_provider import AIProviderError
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.script_generator_service import _parse_ai_json_response
from app.services.youtube_role_context_service import (
    MAX_SEMANTIC_CONTEXT_CHARS,
    build_production_packet,
    build_script_review_packet,
    build_seo_packet,
    build_thumbnail_packet,
)
from scripts.audit_harness_ecosystem import audit as audit_harness_ecosystem

BUILDERS = {
    "build_script_review_packet": build_script_review_packet,
    "build_production_packet": build_production_packet,
    "build_seo_packet": build_seo_packet,
    "build_thumbnail_packet": build_thumbnail_packet,
}
REQUIRED_PRODUCT_CAPABILITIES = (
    "gta6.research.fresh-cloud",
    "gta6.fact-check",
    "gta6.brain.decide",
    "youtube.department.content-strategy",
    "youtube.department.script-review",
    "youtube.department.seo",
    "youtube.department.production-management",
    "youtube.department.thumbnail-strategy",
    "youtube.package.persist",
)


def _assert_compile(paths: list[Path]) -> None:
    for path in paths:
        if not compileall.compile_file(str(path), quiet=1, force=True):
            raise RuntimeError(f"compile failed: {path}")


def _assert_call_signatures(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    checked = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        builder = BUILDERS.get(node.func.id)
        if builder is None:
            continue
        signature = inspect.signature(builder)
        supplied = {kw.arg for kw in node.keywords if kw.arg is not None}
        if any(kw.arg is None for kw in node.keywords):
            raise AssertionError(f"{node.func.id} uses **kwargs; static contract cannot prove compatibility")
        parameters = signature.parameters
        unknown = supplied - set(parameters)
        required = {
            name
            for name, param in parameters.items()
            if param.default is inspect._empty
            and param.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        }
        missing = required - supplied
        if unknown or missing:
            raise AssertionError(
                f"{node.func.id} signature mismatch unknown={sorted(unknown)} missing={sorted(missing)}"
            )
        checked.append({"builder": node.func.id, "line": node.lineno})
    if {item["builder"] for item in checked} != set(BUILDERS):
        raise AssertionError("not every role context builder call was statically validated")
    return {"checked_calls": checked}


def _sample_packets() -> dict[str, Any]:
    claims = [{
        "claim_id": "claim-gate-1",
        "statement": "Official-source fact used for contract validation.",
        "verification_status": "VERIFIED",
        "source_hierarchy": "OFFICIAL_PRIMARY",
        "fact_check_result": "SUPPORTED",
        "fact_check_confidence": 1.0,
        "evidence_refs": ["source:gate"],
    }]
    plan = {
        "title": "GTA VI",
        "objective": "contract validation",
        "audience": "pt-BR",
        "format": "video",
        "tone": "factual",
        "hook": "h",
        "estimated_duration_seconds": 900.0,
        "editorial_evidence_refs": ["claim:claim-gate-1"],
        "audio_requirements": ["voiceover"],
        "visual_requirements": ["evidence-grounded visuals"],
        "scenes": [
            {
                "order": index,
                "narrative_block": f"Bloco {index}",
                "duration_seconds": 30.0,
                "visual_type": "gameplay",
                "visual_description": f"Visual específico {index} baseado em evidência.",
                "narration": "Narração factual de teste.",
                "requirements": ["evidence", "timing"],
                "segment_id": None,
            }
            for index in range(1, 31)
        ],
    }
    common = dict(
        goal_id="gate-goal",
        content_item_id=1,
        script_id=1,
        production_plan_id=1,
        script_text="HOOK\nh\n\nBLOCO\n" + ("texto factual " * 500),
        production_plan=plan,
        claims=claims,
        strategy_output={
            "audience": "BR",
            "angle": "verified",
            "promise": "facts",
            "differentiation": "official evidence",
            "title_direction": "factual",
        },
        full_context_chars=40_000,
    )
    results = {
        "script_review": build_script_review_packet(**common),
        "production_management": build_production_packet(**common),
        "seo": build_seo_packet(title="GTA VI factual", **common),
        "thumbnail": build_thumbnail_packet(
            title="GTA VI factual",
            seo_output={"search_intent": "gta vi", "keywords": ["gta vi"], "rationale": "verified"},
            **common,
        ),
    }
    for role, result in results.items():
        json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True))
        metrics = result["metrics"]
        if metrics["packet_chars"] > MAX_SEMANTIC_CONTEXT_CHARS:
            raise AssertionError(f"{role} exceeded semantic context boundary")
        if not metrics["artifact_refs"] or not metrics["content_hashes"]:
            raise AssertionError(f"{role} lost reconstructable artifact lineage")
    return {role: value["metrics"] for role, value in results.items()}


def _assert_registry_routing() -> dict[str, Any]:
    routes = []
    for capability_id in REQUIRED_PRODUCT_CAPABILITIES:
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if record is None or not record.available:
            raise AssertionError(f"required capability unavailable: {capability_id}")
        if not record.executor_binding or not record.security_boundary or not record.evidence_contract:
            raise AssertionError(f"incomplete boundary/evidence contract: {capability_id}")
        if not record.allowed_actions:
            raise AssertionError(f"missing allowed action: {capability_id}")
        action = record.allowed_actions[0]
        decision = route_harness_request(HarnessRoutingRequest(
            intent=f"pre-live validation for {capability_id}",
            authorized_action=action,
            domain=record.domain,
            required_capability_id=capability_id,
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
        ))
        if decision.selected_capability_id != capability_id:
            raise AssertionError(f"routing escaped capability: {capability_id}")
        if decision.selected_executor_binding != record.executor_binding:
            raise AssertionError(f"executor binding mismatch: {capability_id}")
        from app.services.harness_capability_service import CAPABILITY_CATALOG
        executable_ids = {item.capability_id for item in CAPABILITY_CATALOG}
        if capability_id not in executable_ids:
            raise AssertionError(
                f"Registry-routable capability missing from Harness execution catalog: {capability_id}"
            )
        routes.append({"capability_id": capability_id, "routing_id": decision.routing_id})
    return {"routes": routes}


def _assert_learning_route_contract() -> dict[str, Any]:
    capability_id = "youtube.package.persist"
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None:
        raise AssertionError("youtube.package.persist is not registered")
    decision = route_harness_request(HarnessRoutingRequest(
        intent="persist the verified pre-publication YouTube content package",
        authorized_action="YOUTUBE",
        domain="youtube-department",
        task_class="youtube-package-persist",
        required_capability_id=capability_id,
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=True,
        goal_id="fast-prelive-goal",
    ))
    if decision.selected_capability_id != capability_id:
        raise AssertionError("learning-aware package routing escaped required capability")
    if decision.selected_executor_binding != record.executor_binding:
        raise AssertionError("learning-aware package routing executor mismatch")
    metadata = dict(decision.policy_metadata or {})
    learning = dict(metadata.get("learning_context") or {})
    if learning.get("learning_required") is not True:
        raise AssertionError("package routing did not preserve required Learning Plane participation")
    return {
        "capability_id": capability_id,
        "domain": "youtube-department",
        "task_class": "youtube-package-persist",
        "routing_id": decision.routing_id,
        "learning_required": True,
        "learning_participated": bool(learning.get("learning_participated")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[1]
    initialize_schema()

    _assert_compile([
        root / "app/services/script_generator_service.py",
        root / "app/services/youtube_role_context_service.py",
        root / "scripts/youtube_product_quality_e2e.py",
    ])

    raw='{"hook":"h","introduction":"i","development":[{"heading":"a","body":"b"},{"heading":"c","body":"d"},{"heading":"e","body":"f"}],"conclusion":"c","cta":"x"}'
    assert _parse_ai_json_response("\ufeff```json\n" + raw + "\n```")["hook"] == "h"
    try:
        _parse_ai_json_response("prose\n" + raw)
    except AIProviderError:
        pass
    else:
        raise AssertionError("script parser accepted non-JSON prose wrapper")

    signatures = _assert_call_signatures(root / "scripts/youtube_product_quality_e2e.py")
    packets = _sample_packets()
    routing = _assert_registry_routing()
    learning_route = _assert_learning_route_contract()
    ecosystem = audit_harness_ecosystem()
    required_ecosystem = (
        "ALL_AGENTS_DISCOVERABLE",
        "ALL_CAPABILITIES_ROUTABLE_WHERE_AUTHORIZED",
        "NO_AGENT_WITHOUT_BOUNDARY",
        "NO_DUPLICATE_AUTHORITY",
        "EXECUTOR_BINDINGS_VALID",
    )
    for key in required_ecosystem:
        if not ecosystem.get(key):
            raise AssertionError(f"ecosystem gate failed: {key}")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "status": "PASS",
        "SIGNATURE_CONTRACT_GATE": "PASS",
        "FAST_STATIC_CONTRACT_GATE": "PASS",
        "REGISTRY_ROUTING_GATE": "PASS",
        "LEARNING_ROUTE_CONTRACT_GATE": "PASS",
        "SERIALIZATION_GATE": "PASS",
        **{key: "PASS" for key in required_ecosystem},
        "FAST_PRELIVE_GATE_MS": round(elapsed_ms, 3),
        "signature_contract": signatures,
        "context_packets": packets,
        "routing": routing,
        "learning_route": learning_route,
        "ecosystem_counts": {
            "capabilities": ecosystem["TOTAL_CAPABILITIES_FOUND"],
            "agents": ecosystem["TOTAL_AGENTS_FOUND"],
            "skills": ecosystem["TOTAL_SKILLS_FOUND"],
            "workers": ecosystem["TOTAL_WORKER_ENGINES_FOUND"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key in (
        "SIGNATURE_CONTRACT_GATE",
        "FAST_STATIC_CONTRACT_GATE",
        "REGISTRY_ROUTING_GATE",
        "LEARNING_ROUTE_CONTRACT_GATE",
        "SERIALIZATION_GATE",
        *required_ecosystem,
    ):
        print(f"{key}={result[key]}")
    print(f"FAST_PRELIVE_GATE_MS={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
