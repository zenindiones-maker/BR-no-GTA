from pathlib import Path

from app.services.capability_usage_audit_service import build_capability_usage_audit


ROOT = Path(__file__).resolve().parents[1]

_EXPLICIT_ONLY = (
    ".github/workflows/video-a-render-profile-benchmark.yml",
    ".github/workflows/video-a-render-learning-benchmark.yml",
    ".github/workflows/video-a-real-render-learning-proof.yml",
    ".github/workflows/video-a-governed-promotion.yml",
    ".github/workflows/native-opencode-telegram-recovery-experiment.yml",
    ".github/workflows/opencode-native-ai-proof.yml",
    ".github/workflows/omniroute-opencode-proof.yml",
    ".github/workflows/telegram-opencode-cli-candidate.yml",
    ".github/workflows/telegram-opencode-executor-benchmark.yml",
    ".github/workflows/telegram-provider-learning-experiment.yml",
)


def test_unrelated_expensive_workflows_do_not_start_on_every_branch_push():
    for relative in _EXPLICIT_ONLY:
        text = (ROOT / relative).read_text(encoding="utf-8")
        header = text.split("permissions:", 1)[0]
        assert "workflow_dispatch:" in header, relative
        assert "\n  push:" not in header, relative


def test_capability_usage_audit_classifies_reachability_without_hiding_blockers():
    audit = build_capability_usage_audit()
    assert audit["CAPABILITY_USAGE_AUDIT"] == "PASS"
    assert audit["registered"] == len(audit["records"])
    assert audit["available"] <= audit["registered"]
    assert audit["routable"] <= audit["registered"]
    classifications = {row["classification"] for row in audit["records"]}
    assert classifications <= {
        "ACTIVE_USAGE",
        "REGISTERED_BUT_NEVER_SELECTED",
        "REGISTERED_BUT_UNREACHABLE",
        "BLOCKED_BY_POLICY_OR_AVAILABILITY",
    }
    for capability_id in audit["orphaned"]:
        row = next(item for item in audit["records"] if item["capability_id"] == capability_id)
        assert row["available"] is True
        assert row["routable"] is False
