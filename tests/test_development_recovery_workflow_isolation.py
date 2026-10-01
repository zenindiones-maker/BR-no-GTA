from __future__ import annotations

from pathlib import Path
import re

from app.services.development_continuity_policy_service import DevelopmentContinuityPolicy
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def test_development_checkpoint_capability_is_bounded_noncanonical():
    record = GLOBAL_CAPABILITY_REGISTRY.get("development.checkpoint.persist")
    assert record is not None
    assert record.allowed_actions == ("DEVELOPMENT",)
    assert record.authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.side_effect_class == "BOUNDED_MUTATION"
    assert record.default_write_scope == ("recovery/dev/**",)
    assert "work/gate6f-analytics-learning" not in record.default_write_scope
    assert "main" not in record.default_write_scope
    assert record.supports_resume is True


def test_recovery_refs_are_absent_from_all_push_workflow_triggers():
    root = Path(".github/workflows")
    offenders = []
    for path in root.glob("*.y*ml"):
        text = path.read_text(encoding="utf-8")
        # Any explicit recovery/dev trigger is forbidden. Current workflows are
        # branch allowlisted; wildcard push branches that could include recovery
        # refs are also forbidden.
        if "recovery/dev/" in text:
            offenders.append(str(path))
        if re.search(r"branches:\s*\n\s*-\s*['\"]?\*\*?['\"]?", text):
            offenders.append(str(path))
    assert offenders == []
    p = DevelopmentContinuityPolicy()
    assert p.recovery_ref_can_trigger_production is False
