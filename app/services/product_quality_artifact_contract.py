from __future__ import annotations

from typing import Any


PRODUCT_QUALITY_E2E_SCHEMA = "YouTubeProductQualityE2E/v1"
PRODUCT_QUALITY_COMPATIBILITY_SCHEMA = (
    "ProductQualityArtifactCompatibility/v1"
)

_REQUIRED_TOP_LEVEL_FIELDS = frozenset({
    "status",
    "mission_id",
    "goal_id",
    "content_item_id",
    "script_id",
    "production_plan_id",
    "youtube_entity_id",
    "claims",
    "production_plan",
    "youtube_package",
    "structured_specialist_outputs",
    "metrics",
})

_REQUIRED_METRIC_FIELDS = frozenset({
    "verified_claims",
    "script_word_count",
    "scene_count",
    "max_scene_seconds",
    "package_evidence_refs",
    "target_duration_seconds",
    "generic_scene_ratio",
    "title_card_ratio",
    "media_resolvable_ratio",
    "evidence_to_scene_coverage",
})

_RATIO_FIELDS = frozenset({
    "generic_scene_ratio",
    "title_card_ratio",
    "media_resolvable_ratio",
    "evidence_to_scene_coverage",
})


def assess_product_quality_artifact(
    artifact: Any,
) -> dict[str, Any]:
    """Validate whether an imported Product E2E artifact may be resumed.

    This is a compatibility gate, not an authority boundary. A legacy or
    malformed artifact may still contribute independently validated upstream
    evidence, but it must never be relabeled as the current product contract.
    """
    reasons: list[str] = []
    if not isinstance(artifact, dict):
        return {
            "schema": PRODUCT_QUALITY_COMPATIBILITY_SCHEMA,
            "compatible": False,
            "expected_schema": PRODUCT_QUALITY_E2E_SCHEMA,
            "observed_schema": None,
            "missing_top_level_fields": sorted(
                _REQUIRED_TOP_LEVEL_FIELDS
            ),
            "missing_metric_fields": sorted(
                _REQUIRED_METRIC_FIELDS
            ),
            "invalid_metric_fields": [],
            "reasons": ["ARTIFACT_NOT_OBJECT"],
        }

    observed_schema = str(artifact.get("schema") or "").strip() or None
    if observed_schema != PRODUCT_QUALITY_E2E_SCHEMA:
        reasons.append("SCHEMA_VERSION_MISMATCH")

    missing_top = sorted(
        field
        for field in _REQUIRED_TOP_LEVEL_FIELDS
        if field not in artifact
    )
    if missing_top:
        reasons.append("REQUIRED_TOP_LEVEL_FIELDS_MISSING")

    if str(artifact.get("status") or "") != "PASS":
        reasons.append("PRODUCT_STATUS_NOT_PASS")

    metrics = artifact.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        if "metrics" in artifact:
            reasons.append("METRICS_NOT_OBJECT")
    missing_metrics = sorted(
        field
        for field in _REQUIRED_METRIC_FIELDS
        if field not in metrics
    )
    if missing_metrics:
        reasons.append("REQUIRED_METRICS_MISSING")

    invalid_metrics: list[str] = []
    for field in sorted(_REQUIRED_METRIC_FIELDS - set(missing_metrics)):
        value = metrics.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid_metrics.append(field)
            continue
        if field in _RATIO_FIELDS and not 0.0 <= float(value) <= 1.0:
            invalid_metrics.append(field)
    if invalid_metrics:
        reasons.append("METRIC_TYPE_OR_RANGE_INVALID")

    for field in (
        "mission_id",
        "goal_id",
        "content_item_id",
        "script_id",
        "production_plan_id",
        "youtube_entity_id",
    ):
        if field in artifact and artifact.get(field) in (None, ""):
            reasons.append(f"REQUIRED_IDENTITY_EMPTY:{field}")

    return {
        "schema": PRODUCT_QUALITY_COMPATIBILITY_SCHEMA,
        "compatible": not reasons,
        "expected_schema": PRODUCT_QUALITY_E2E_SCHEMA,
        "observed_schema": observed_schema,
        "missing_top_level_fields": missing_top,
        "missing_metric_fields": missing_metrics,
        "invalid_metric_fields": invalid_metrics,
        "reasons": reasons,
    }
