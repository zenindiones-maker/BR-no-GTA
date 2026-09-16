from pathlib import Path

readiness_path = Path("app/services/youtube_publication_readiness_service.py")
google_path = Path("app/services/google_youtube_publication_service.py")
server_path = Path("app/integrations/deepseek_harness/server.py")
test_path = Path("tests/test_deepseek_harness.py")

# 1. Readiness must fail closed when a prior public side effect is unresolved.
text = readiness_path.read_text(encoding="utf-8")
old = "from app.database.youtube_repository import get_youtube_publication\n"
new = (
    "from app.database.youtube_repository import get_youtube_publication\n"
    "from app.database.youtube_public_transition_repository import (\n"
    "    get_youtube_public_transition,\n"
    ")\n"
)
assert text.count(old) == 1
text = text.replace(old, new)
old = """    if not isinstance(youtube_url, str) or not youtube_url.strip():
        reasons.append("youtube_url_missing")

    goal_id: str | None = None
"""
new = """    if not isinstance(youtube_url, str) or not youtube_url.strip():
        reasons.append("youtube_url_missing")
    public_transition = get_youtube_public_transition(publication_id)
    public_transition_status = (
        public_transition.get("status")
        if isinstance(public_transition, dict)
        else None
    )
    if public_transition_status in {"EXECUTING", "REMOTE_STATE_UNCERTAIN"}:
        reasons.append("public_transition_requires_remote_reconciliation")

    goal_id: str | None = None
"""
assert text.count(old) == 1
text = text.replace(old, new)
old = '        "approval_granted": False,\n        "boundary": "READ_ONLY_NO_PUBLICATION_AUTHORITY",\n'
new = (
    '        "approval_granted": False,\n'
    '        "public_transition_status": public_transition_status,\n'
    '        "boundary": "READ_ONLY_NO_PUBLICATION_AUTHORITY",\n'
)
assert text.count(old) == 1
text = text.replace(old, new)
readiness_path.write_text(text, encoding="utf-8")

# 2. Add a Google-backed remote visibility reconciliation wrapper.
text = google_path.read_text(encoding="utf-8")
old = """from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    upload_youtube_publication,
)
"""
new = """from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    reconcile_youtube_publication_visibility,
    upload_youtube_publication,
)
"""
assert text.count(old) == 1
text = text.replace(old, new)
anchor = "\n\ndef process_next_youtube_publication(\n"
assert text.count(anchor) == 1
wrapper = '''\n\ndef reconcile_youtube_publication_visibility_with_google(\n    *,\n    publication_id: int,\n    token_file: str | None = None,\n    client_secrets_file: str | None = None,\n    authorization_runner: Callable[[Any], Any] | None = None,\n    request: Any | None = None,\n) -> dict[str, Any]:\n    """Read remote visibility and reconcile an uncertain public transition."""\n    if not isinstance(publication_id, int) or isinstance(publication_id, bool) or publication_id <= 0:\n        raise ValueError("publication_id must be a positive integer")\n    publication = get_youtube_publication(publication_id)\n    if publication is None:\n        raise ValueError(f"YouTube publication not found: {publication_id}")\n    publisher = _create_google_publisher(\n        token_file=token_file,\n        client_secrets_file=client_secrets_file,\n        authorization_runner=authorization_runner,\n        request=request,\n    )\n    return reconcile_youtube_publication_visibility(\n        publication_id=publication_id,\n        publisher=publisher,\n    )\n'''
text = text.replace(anchor, wrapper + anchor)
google_path.write_text(text, encoding="utf-8")

# 3. MCP: explicit user approval, read-only preview and recovery reconciliation.
text = server_path.read_text(encoding="utf-8")
old = """from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)
"""
new = """from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
    reconcile_youtube_publication_visibility_with_google,
)
"""
assert text.count(old) == 1
text = text.replace(old, new)
old = """from app.services.youtube_cloud_upload_service import (
    dispatch_targeted_private_upload,
    reconcile_targeted_private_upload,
)
"""
new = """from app.services.youtube_cloud_upload_service import (
    dispatch_targeted_private_upload,
    reconcile_targeted_private_upload,
)
from app.services.youtube_publication_readiness_service import (
    build_youtube_publication_preview,
)
"""
assert text.count(old) == 1
text = text.replace(old, new)
old = '''@mcp.tool()\ndef br_youtube_pode_postar(publication_id: int) -> str:\n    """Route and authorize one exact uploaded -> public transition."""\n    result = publish_targeted_publication(publication_id)\n    return _json_result(\n        operation="br_youtube_pode_postar",\n        result=result,\n    )\n\n\n@mcp.tool()\ndef br_youtube_publish(publication_id: int) -> str:\n'''
new = '''@mcp.tool()\ndef br_youtube_publication_preview(publication_id: int) -> str:\n    """Read exact publication readiness without granting publication authority."""\n    result = build_youtube_publication_preview(publication_id)\n    return _json_result(\n        operation="br_youtube_publication_preview",\n        result=result,\n    )\n\n\n@mcp.tool()\ndef br_youtube_publication_reconcile(publication_id: int) -> str:\n    """Safely reconcile an uncertain prior user-approved public transition."""\n    result = reconcile_youtube_publication_visibility_with_google(\n        publication_id=publication_id,\n    )\n    return _json_result(\n        operation="br_youtube_publication_reconcile",\n        result=result,\n    )\n\n\n@mcp.tool()\ndef br_youtube_pode_postar(publication_id: int) -> str:\n    """Execute explicit user approval for one exact uploaded Publication."""\n    result = publish_targeted_publication(\n        publication_id,\n        approval_source="user",\n        approval_operation="br_youtube_pode_postar",\n    )\n    return _json_result(\n        operation="br_youtube_pode_postar",\n        result=result,\n    )\n\n\n@mcp.tool()\ndef br_youtube_publish(publication_id: int) -> str:\n'''
assert text.count(old) == 1
text = text.replace(old, new)
server_path.write_text(text, encoding="utf-8")

# 4. MCP regression tests follow the explicit approval/readiness contract.
text = test_path.read_text(encoding="utf-8")
old_names = '"br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_reconcile","br_youtube_publish_next"'
new_names = '"br_youtube_publication_preview","br_youtube_publication_reconcile","br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_reconcile","br_youtube_publish_next"'
assert text.count(old_names) == 1
text = text.replace(old_names, new_names)
old = '''def test_youtube_pode_postar_uses_targeted_harness_publication_boundary(monkeypatch):\n    captured = {}\n\n    def fake(publication_id):\n        captured["publication_id"] = publication_id\n        return {\n            "publication": {"id": publication_id, "status": "published"},\n            "routing": {"selected_capability_id": "youtube.publish-public"},\n            "authorization_id": "auth-publication-42",\n            "canonical_execution_result": {"success": True},\n        }\n\n    monkeypatch.setattr(server, "publish_targeted_publication", fake)\n    payload = json.loads(server.br_youtube_pode_postar(publication_id=42))\n    assert captured["publication_id"] == 42\n    assert payload["result"]["publication"]["status"] == "published"\n    assert payload["result"]["routing"]["selected_capability_id"] == "youtube.publish-public"\n    assert payload["result"]["canonical_execution_result"]["success"] is True\n\n\n'''
new = '''def test_youtube_publication_preview_is_read_only(monkeypatch):\n    captured = {}\n\n    def fake(publication_id):\n        captured["publication_id"] = publication_id\n        return {\n            "publication_id": publication_id,\n            "PUBLICATION_READY": True,\n            "approval_granted": False,\n            "boundary": "READ_ONLY_NO_PUBLICATION_AUTHORITY",\n        }\n\n    monkeypatch.setattr(server, "build_youtube_publication_preview", fake)\n    payload = json.loads(server.br_youtube_publication_preview(publication_id=42))\n    assert captured["publication_id"] == 42\n    assert payload["result"]["PUBLICATION_READY"] is True\n    assert payload["result"]["approval_granted"] is False\n\n\ndef test_youtube_publication_reconcile_targets_exact_publication(monkeypatch):\n    captured = {}\n\n    def fake(*, publication_id):\n        captured["publication_id"] = publication_id\n        return {"id": publication_id, "status": "published"}\n\n    monkeypatch.setattr(server, "reconcile_youtube_publication_visibility_with_google", fake)\n    payload = json.loads(server.br_youtube_publication_reconcile(publication_id=42))\n    assert captured["publication_id"] == 42\n    assert payload["result"]["status"] == "published"\n\n\ndef test_youtube_pode_postar_uses_targeted_harness_publication_boundary(monkeypatch):\n    captured = {}\n\n    def fake(publication_id, **kwargs):\n        captured["publication_id"] = publication_id\n        captured.update(kwargs)\n        return {\n            "publication": {"id": publication_id, "status": "published"},\n            "routing": {"selected_capability_id": "youtube.publish-public"},\n            "authorization_id": "auth-publication-42",\n            "canonical_execution_result": {"success": True},\n        }\n\n    monkeypatch.setattr(server, "publish_targeted_publication", fake)\n    payload = json.loads(server.br_youtube_pode_postar(publication_id=42))\n    assert captured["publication_id"] == 42\n    assert captured["approval_source"] == "user"\n    assert captured["approval_operation"] == "br_youtube_pode_postar"\n    assert payload["result"]["publication"]["status"] == "published"\n    assert payload["result"]["routing"]["selected_capability_id"] == "youtube.publish-public"\n    assert payload["result"]["canonical_execution_result"]["success"] is True\n\n\n'''
assert text.count(old) == 1
text = text.replace(old, new)
test_path.write_text(text, encoding="utf-8")
