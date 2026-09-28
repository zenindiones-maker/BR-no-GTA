from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "agent-tooling" / "bootstrap.sh"


def test_bootstrap_exposes_pinned_claude_code_mode():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "all|codex|claude|addy|higgsfield" in text
    assert 'version="2.1.283"' in text
    assert "https://github.com/anthropics/claude-code/releases/download/v${version}/${asset}" in text
    assert "db404a91bec8baffb53463166fdc8bf579208a527d60afc2d984d7507dc0c2f9" in text
    assert "a2e7d497d40041d7eca8f8fd1d77405a6501ff8b1a61fa02a0e95c458824a43e" in text
    assert "sha256sum -c -" in text
    assert "claude --version" in text
    assert "ANTHROPIC_API_KEY" not in text
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in text


def test_claude_install_target_exists_before_binary_install():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    mkdir_index = text.index('mkdir -p "$tooling_root/bin"')
    install_index = text.index('install -m 0755 "$tmpdir/claude" "$tooling_root/bin/claude-$version"')
    assert mkdir_index < install_index


def test_claude_only_mode_does_not_require_node_or_npm():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'if [[ "$mode" = all || "$mode" = codex || "$mode" = higgsfield ]]; then' in text


if __name__ == "__main__":
    test_bootstrap_exposes_pinned_claude_code_mode()
    test_claude_install_target_exists_before_binary_install()
    test_claude_only_mode_does_not_require_node_or_npm()
    print("CLAUDE_CODE_BOOTSTRAP_CONTRACT=PASS")
