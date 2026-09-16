from pathlib import Path

server_path = Path("app/integrations/deepseek_harness/server.py")
test_path = Path("tests/test_deepseek_harness.py")

server = server_path.read_text()
old_import = '''from app.services.google_youtube_publication_service import (
    make_youtube_publication_public_with_google,
    process_next_youtube_publication,
)
'''
new_import = '''from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)
from app.services.harness_youtube_publication_service import (
    publish_targeted_publication,
    upload_targeted_publication,
)
'''
assert server.count(old_import) == 1, "expected exact legacy YouTube import block"
server = server.replace(old_import, new_import)

old_tools = '''@mcp.tool()
def br_youtube_pode_postar(publication_id: int) -> str:
    """
    Explicit authorization gate for public YouTube publication.

    This operation is intentionally separate from the GTA6 Brain YOUTUBE
    action. YOUTUBE may upload pending content, while this operation
    authorizes the existing uploaded -> published transition.
    """
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={"publication_id": publication_id},
    )
    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
        authorization=authorization,
    )
    return _json_result(
        operation="br_youtube_pode_postar",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_next() -> str:
'''
new_tools = '''@mcp.tool()
def br_youtube_pode_postar(publication_id: int) -> str:
    """Route and authorize one exact uploaded -> public transition."""
    result = publish_targeted_publication(publication_id)
    return _json_result(
        operation="br_youtube_pode_postar",
        result=result,
    )


@mcp.tool()
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
assert server.count(old_tools) == 1, "expected exact legacy publication tool block"
server = server.replace(old_tools, new_tools)
server_path.write_text(server)

tests = test_path.read_text()
old_set = '''    assert names == {"br_observe","br_knowledge_query","br_research_run","br_route","br_editorial_process_next","br_execution_process_next","br_gta6_monitor_run_once","br_master_run_once","br_youtube_pode_postar","br_youtube_publish_next","br_capabilities_discover","br_capability_execute"}
'''
new_set = '''    assert names == {"br_observe","br_knowledge_query","br_research_run","br_route","br_editorial_process_next","br_execution_process_next","br_gta6_monitor_run_once","br_master_run_once","br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_next","br_capabilities_discover","br_capability_execute"}
'''
assert tests.count(old_set) == 1, "expected exact operational tool set assertion"
tests = tests.replace(old_set, new_set)

old_test = '''def test_youtube_pode_postar_issues_publication_authorization(monkeypatch):
    captured={}
    def fake(*,publication_id,authorization):
        captured["auth"]=authorization; return {"id":publication_id,"status":"published"}
    monkeypatch.setattr(server,"make_youtube_publication_public_with_google",fake)
    payload=json.loads(server.br_youtube_pode_postar(publication_id=42))
    assert payload["result"]["status"] == "published"
    assert captured["auth"].authorized_action == "PUBLICATION"
    assert captured["auth"].subject == "youtube:publication:42"


'''
new_test = '''def test_youtube_pode_postar_uses_targeted_harness_publication_boundary(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "publication": {"id": publication_id, "status": "published"},
            "routing": {"selected_capability_id": "youtube.publish-public"},
            "authorization_id": "auth-publication-42",
            "canonical_execution_result": {"success": True},
        }

    monkeypatch.setattr(server, "publish_targeted_publication", fake)
    payload = json.loads(server.br_youtube_pode_postar(publication_id=42))
    assert captured["publication_id"] == 42
    assert payload["result"]["publication"]["status"] == "published"
    assert payload["result"]["routing"]["selected_capability_id"] == "youtube.publish-public"
    assert payload["result"]["canonical_execution_result"]["success"] is True


def test_youtube_publish_uses_targeted_harness_private_upload_boundary(monkeypatch):
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
assert tests.count(old_test) == 1, "expected exact legacy br_youtube_pode_postar test"
tests = tests.replace(old_test, new_test)
test_path.write_text(tests)
