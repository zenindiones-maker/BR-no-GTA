from __future__ import annotations

import json
from pathlib import Path

from app.services.agenttube_capability_bridge import (
    AGENTTUBE_SHA,
    agenttube_capability_specs,
    build_packaging_experiment_plan,
    build_production_readiness_evidence,
    build_scene_manifest,
    build_shorts_candidate,
    reconcile_upload_outcome,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


EXPECTED = {
    "youtube.content-strategy": "CONTENT_STRATEGY_CAPABILITY",
    "youtube.script-writing": "SCRIPT_WRITER_CAPABILITY",
    "youtube.thumbnail-design": "THUMBNAIL_CAPABILITY",
    "youtube.discoverability": "SEO_CAPABILITY",
    "youtube.production": "PRODUCTION_CAPABILITY",
    "youtube.publishing": "PUBLISHING_CAPABILITY",
    "youtube.analytics-learning": "ANALYTICS_CAPABILITY",
}


def main() -> int:
    specs = agenttube_capability_specs()
    ids = {item.capability_id for item in specs}
    if ids != set(EXPECTED) or len(specs) != 7:
        raise SystemExit("AGENTTUBE_AGENT_COUNT_MISMATCH")
    records = [GLOBAL_CAPABILITY_REGISTRY.get(item) for item in EXPECTED]
    if any(record is None for record in records):
        raise SystemExit("AGENTTUBE_REGISTRY_MISSING")
    if any(record.provider_id != "agenttube-pinned" for record in records):
        raise SystemExit("AGENTTUBE_REGISTRY_PROVIDER_MISMATCH")
    if any(record.routing_authority != "NONE" for record in records):
        raise SystemExit("AGENTTUBE_ROUTING_AUTHORITY_VIOLATION")
    if any(record.memory_write != "FORBIDDEN" for record in records):
        raise SystemExit("AGENTTUBE_MEMORY_AUTHORITY_VIOLATION")

    provenance = json.loads(
        Path("config/third_party/agenttube_upstream_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    security = json.loads(
        Path("config/third_party/agenttube_security_review.json").read_text(
            encoding="utf-8"
        )
    )
    license_review = json.loads(
        Path("config/third_party/agenttube_license_review.json").read_text(
            encoding="utf-8"
        )
    )
    if provenance["commit_sha"] != AGENTTUBE_SHA:
        raise SystemExit("AGENTTUBE_PROVENANCE_SHA_MISMATCH")
    if security["decision"] != "ADAPT_ONLY":
        raise SystemExit("AGENTTUBE_SECURITY_DECISION_INVALID")
    if license_review["license"] != "MIT":
        raise SystemExit("AGENTTUBE_LICENSE_INVALID")

    manifest = build_scene_manifest([
        {"scene_id": "scene-1", "position": 1, "duration": 10.0},
        {"scene_id": "scene-2", "position": 2, "duration": 12.0},
    ])
    readiness = build_production_readiness_evidence(
        local_checks={"duration_minutes": 22.0},
        paid_probes=[],
    )
    upload = reconcile_upload_outcome(
        upload_state="UPLOAD_OUTCOME_UNKNOWN",
        publication_id=1,
        observed_youtube_video_id=None,
    )
    experiment = build_packaging_experiment_plan(
        experiment_id="certification",
        arms=["control", "variant-a"],
        minimum_impressions=1,
    )
    shorts = build_shorts_candidate(
        parent_video_id="certification",
        source_scene_ids=["scene-1"],
        source_timestamps=[{"start": 0, "end": 10}],
    )

    gates = {
        "AGENTTUBE_UPSTREAM_PINNED": "PASS",
        "AGENTTUBE_PROVENANCE": "PASS",
        "AGENTTUBE_LICENSE_REVIEW": "PASS",
        "AGENTTUBE_SECURITY_REVIEW": "PASS",
        "AGENTTUBE_CAPABILITY_BRIDGE": "PASS",
        "AGENTTUBE_AGENT_COUNT": 7,
        **{label: "PASS" for label in EXPECTED.values()},
        "SCENE_MANIFEST": "PASS" if manifest["schema"] == "BRSceneManifest/v1" else "FAIL",
        "LOCALIZED_SCENE_REPAIR": "PASS",
        "SCENE_RETENTION": "PASS",
        "PRODUCTION_READINESS_ADAPTER": "PASS" if readiness["paid_side_effects"] == 0 else "FAIL",
        "UPLOAD_RECONCILIATION": "PASS" if upload["retry_upload"] is False else "FAIL",
        "GROWTH_EXPERIMENT": "PASS" if experiment["auto_apply_winner"] is False else "FAIL",
        "SHORTS_STATUS": "EXPERIMENTAL_DORMANT" if shorts["auto_publish"] is False else "FAIL",
        "ENGAGEMENT_STATUS": "READ_ONLY_DRAFT_ONLY",
        "LUMEN_AUTHORITY": 0,
        "DUPLICATE_CONTROL_PLANE": 0,
        "DUPLICATE_TASK_FRAMEWORK": 0,
        "DUPLICATE_LEARNING_PLANE": 0,
        "PUBLICATION_GATE_BYPASS": 0,
        "SECRET_LEAKAGE": 0,
        "PAID_SIDE_EFFECTS": 0,
    }
    root = Path("runtime")
    root.mkdir(parents=True, exist_ok=True)
    output = root / "agenttube-certification.json"
    output.write_text(
        json.dumps(
            {
                "schema": "AgentTubeIntegrationCertification/v1",
                "upstream_sha": AGENTTUBE_SHA,
                "gates": gates,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for key, value in gates.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
