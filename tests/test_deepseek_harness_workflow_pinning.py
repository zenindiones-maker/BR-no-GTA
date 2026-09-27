from pathlib import Path


def test_deepseek_native_workflow_pins_compatible_host_and_mcp_plugin():
    workflow = Path(".github/workflows/deepseek-harness.yml").read_text(
        encoding="utf-8"
    )
    assert 'DSH_VERSION: "0.1.7-rc.2"' in workflow
    assert 'DSH_MCP_CLIENT_VERSION: "0.1.7-rc.2"' in workflow
    assert '@deepseek-ai/dsh-mcp-client@0.0.1-rc.1' not in workflow
    assert "npx --yes @deepseek-ai/dsh " not in workflow
    assert '"@deepseek-ai/dsh@${DSH_VERSION}"' in workflow
    assert (
        '"@deepseek-ai/dsh-mcp-client@${DSH_MCP_CLIENT_VERSION}"'
        in workflow
    )
    assert "allow-version" not in workflow
    assert "accept-risk" not in workflow


def test_deepseek_native_workflow_verifies_registry_versions_before_install():
    workflow = Path(".github/workflows/deepseek-harness.yml").read_text(
        encoding="utf-8"
    )
    assert 'npm view "@deepseek-ai/dsh@${DSH_VERSION}" version' in workflow
    assert (
        'npm view "@deepseek-ai/dsh-mcp-client@${DSH_MCP_CLIENT_VERSION}"'
        in workflow
    )
    assert "mcp-client-package.json" in workflow
