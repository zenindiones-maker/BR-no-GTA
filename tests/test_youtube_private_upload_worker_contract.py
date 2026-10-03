from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_telegram_review_verification_heredoc_imports_os_before_using_environ():
    text=(ROOT/".github"/"workflows"/"youtube-private-upload-worker.yml").read_text(encoding="utf-8")
    marker="      - name: Deliver mandatory Telegram review package"
    block=text.split(marker,1)[1].split("      - name:",1)[0]
    assert "import os" in block
    assert 'os.environ["EXPECTED_PUBLICATION_ID"]' in block
