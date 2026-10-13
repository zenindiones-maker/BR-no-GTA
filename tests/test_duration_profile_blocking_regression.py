import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run001_longform_no_padding_qa import validate_no_padding


def test_duration_qa_rejects_incompatible_product_profile():
    with pytest.raises(RuntimeError):
        validate_no_padding(
            job={
                "product_profile": "incompatible_profile",
                "render_job_id": 1,
                "youtube_publication": False,
            },
            edit_qa={},
        )


@pytest.mark.parametrize(
    ("script", "marker"),
    [
        (
            "scripts/run001_longform_no_padding_qa.py",
            "LONG_FORM_NO_PADDING_QA=BLOCKED",
        ),
        (
            "scripts/run001_professional_finalize_qa.py",
            "PROFESSIONAL_FINAL_QA=BLOCKED",
        ),
    ],
)
def test_incompatible_profile_cli_exits_nonzero_and_writes_blocked_receipt(
    tmp_path: Path, script: str, marker: str
):
    folder = tmp_path / "artifact"
    folder.mkdir()
    (folder / "render.mp4").write_bytes(b"fixture")
    (folder / "render-job.json").write_text(
        json.dumps({"product_profile": "incompatible_profile"}),
        encoding="utf-8",
    )
    (folder / "edit-qa.json").write_text("{}", encoding="utf-8")

    import os

    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            script,
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert marker in result.stdout, result.stdout
    receipt_name = (
        "no-artificial-padding-qa.json"
        if "longform_no_padding" in script
        else "audiovisual-qa.json"
    )
    receipt = folder / receipt_name
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload.get("status") == "BLOCKED"
    reason = payload.get("reason", "")
    assert reason.startswith("BLOCKED_INCOMPATIBLE_PRODUCT_PROFILE")

    if "professional_finalize" in script:
        assert payload.get("stage") == "professional_final_branded"
        assert payload.get("human_editorial_approval") == "PENDING"
        assert (
            payload.get("youtube_publication_authority")
            == "BLOCKED_PENDING_HUMAN_APPROVAL"
        )
