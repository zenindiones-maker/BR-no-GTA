from pathlib import Path

registry_path = Path("app/services/global_capability_registry_base.py")
server_path = Path("app/integrations/deepseek_harness/server.py")
test_path = Path("tests/test_deepseek_harness.py")

registry = registry_path.read_text(encoding="utf-8")
old_registry = '''            implementation="YouTube publisher/upload orchestration",
            input_contract="authorized publication/video spec",
            output_contract="private uploaded YouTube publication",
            requirements=("YouTube credentials", "video artifact"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("YOUTUBE",),
            policy_tags=("youtube", "upload", "private", "publication"),
            security_boundary="upload boundary remains subordinate to Harness flow",
            executor_binding="app.services.youtube_publication_orchestration",
            evidence_contract="YouTube publication record/provider result",
'''
new_registry = '''            implementation="Harness-governed GitHub Actions private-upload dispatcher/reconciler",
            input_contract="exact pending publication + QA-proven GitHub media artifact locator",
            output_contract="cloud execution identity then private uploaded YouTube publication",
            requirements=("YouTube OAuth secrets in GitHub Actions", "QA-proven render artifact", "canonical SQLite publication"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("YOUTUBE",),
            policy_tags=("youtube", "upload", "private", "publication", "cloud", "targeted"),
            security_boundary="Harness routes exact publication; canonical DB claims before cloud dispatch; worker verifies artifact hash/QA/lineage and cannot publish public",
            executor_binding="app.services.youtube_cloud_upload_service.dispatch_targeted_private_upload",
            evidence_contract="persisted cloud execution + YouTube identity + render artifact evidence",
'''
assert registry.count(old_registry) == 1, "expected exact youtube.upload-private Registry block"
registry = registry.replace(old_registry, new_registry)
registry_path.write_text(registry, encoding="utf-8")

server = server_path.read_text(encoding="utf-8")
old_import = '''from app.services.harness_youtube_publication_service import (
    publish_targeted_publication,
    upload_targeted_publication,
)
'''
new_import = '''from app.services.harness_youtube_publication_service import (
    publish_targeted_publication,
)
from app.services.youtube_cloud_upload_service import (
    dispatch_targeted_private_upload,
    reconcile_targeted_private_upload,
)
'''
assert server.count(old_import) == 1, "expected exact Harness YouTube import block"
server = server.replace(old_import, new_import)
old_tool = '''@mcp.tool()
def br_youtube_publish(publication_id: int) -> str:
    """Route and upload one exact persisted YouTube Publication as private."""
    result = upload_targeted_publication(publication_id)
    return _json_result(
        operation="br_youtube_publish",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_next() -> str:
'''
new_tool = '''@mcp.tool()
def br_youtube_publish(publication_id: int) -> str:
    """Dispatch one exact Publication to the Harness-governed cloud uploader."""
    result = dispatch_targeted_private_upload(publication_id)
    return _json_result(
        operation="br_youtube_publish",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_reconcile(publication_id: int) -> str:
    """Reconcile one exact private-upload cloud run into canonical state."""
    result = reconcile_targeted_private_upload(publication_id)
    return _json_result(
        operation="br_youtube_publish_reconcile",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_next() -> str:
'''
assert server.count(old_tool) == 1, "expected exact targeted YouTube MCP tool"
server = server.replace(old_tool, new_tool)
server_path.write_text(server, encoding="utf-8")

tests = test_path.read_text(encoding="utf-8")
old_names = '"br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_next"'
new_names = '"br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_reconcile","br_youtube_publish_next"'
assert tests.count(old_names) == 1, "expected operational YouTube tool names"
tests = tests.replace(old_names, new_names)
old_test = '''def test_youtube_publish_uses_targeted_harness_private_upload_boundary(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "publication": {"id": publication_id, "status": "uploaded"},
            "routing": {"selected_capability_id": "youtube.upload-private"},
            "authorization_id": "auth-youtube-43",
            "canonical_execution_result": {"success": True},
        }

    monkeypatch.setattr(server, "upload_targeted_publication", fake)
    payload = json.loads(server.br_youtube_publish(publication_id=43))
    assert captured["publication_id"] == 43
    assert payload["result"]["publication"]["status"] == "uploaded"
    assert payload["result"]["routing"]["selected_capability_id"] == "youtube.upload-private"
    assert payload["result"]["canonical_execution_result"]["success"] is True


'''
new_test = '''def test_youtube_publish_dispatches_exact_cloud_target(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "status": "IN_PROGRESS",
            "publication_id": publication_id,
            "upload_run_id": 35050000001,
            "canonical_execution_result": {"success": True},
        }

    monkeypatch.setattr(server, "dispatch_targeted_private_upload", fake)
    payload = json.loads(server.br_youtube_publish(publication_id=43))
    assert captured["publication_id"] == 43
    assert payload["result"]["status"] == "IN_PROGRESS"
    assert payload["result"]["upload_run_id"] == 35050000001
    assert payload["result"]["canonical_execution_result"]["success"] is True


def test_youtube_publish_reconcile_targets_exact_publication(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "status": "UPLOADED",
            "publication": {"id": publication_id, "status": "uploaded"},
            "upload_run_id": 35050000001,
        }

    monkeypatch.setattr(server, "reconcile_targeted_private_upload", fake)
    payload = json.loads(server.br_youtube_publish_reconcile(publication_id=43))
    assert captured["publication_id"] == 43
    assert payload["result"]["status"] == "UPLOADED"
    assert payload["result"]["publication"]["id"] == 43


'''
assert tests.count(old_test) == 1, "expected exact local targeted upload MCP test"
tests = tests.replace(old_test, new_test)
test_path.write_text(tests, encoding="utf-8")
