from scripts.task02_deterministic_team import _category
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

def test_deterministic_workers_are_not_semantic():
    det=GLOBAL_CAPABILITY_REGISTRY.get("agent-office.deterministic-analysis")
    hermes=GLOBAL_CAPABILITY_REGISTRY.get("collaboration.hermes.execute")
    assert det is not None and _category(det)=="MODEL_INDEPENDENT_DETERMINISTIC"
    assert hermes is not None and _category(hermes)!="MODEL_DEPENDENT_SEMANTIC"

def test_addy_semantic_skill_remains_semantic():
    rows=[r for r in GLOBAL_CAPABILITY_REGISTRY.all() if str(r.capability_id).startswith("addy:debugging")]
    assert rows
    assert any(_category(r)=="MODEL_DEPENDENT_SEMANTIC" for r in rows)
