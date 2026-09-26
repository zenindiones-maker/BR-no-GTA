import pytest
from app.services.harness_worker_registry_bridge import manifest_from_capability_registry
def test_real_registry_agent_office_manifest_is_subordinate_and_pinned():
 m=manifest_from_capability_registry("agent-office.codex.bounded-development",worker_build_id="build-sha")
 assert m.authority=="NONE" and m.worker_build_id=="build-sha"
 assert m.capabilities[0].capability_id=="agent-office.codex.bounded-development"
 assert m.executor_binding.endswith("execute_authorized_agent_office_specialist")
def test_provider_layer_cannot_become_worker_manifest():
 from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
 providers=[r.capability_id for r in GLOBAL_CAPABILITY_REGISTRY.all() if str(r.capability_type).upper()=="PROVIDER"]
 if not providers:pytest.skip("registry exposes providers through separate provider registry")
 with pytest.raises(PermissionError,match="PROVIDER_IS_NOT_WORKER"):manifest_from_capability_registry(providers[0],worker_build_id="b")
