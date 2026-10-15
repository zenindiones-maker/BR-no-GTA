"""Regression tests for identity-bound edit QA checkpoint validation."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.edit_checkpoint_guard import validate_edit_checkpoint, CheckpointValidationError


class EditCheckpointGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "output" / "execution-123"
        self.root.mkdir(parents=True)
        (self.root / "render-job.json").write_text(json.dumps({
            "execution_id": "execution-123",
            "render_job_id": 456,
            "video_id": 789,
        }), encoding="utf-8")

    def write_edit_qa(self, *, execution_id="execution-123", render_job_id=456):
        (self.root / "edit-qa.json").write_text(json.dumps({
            "status": "PASS",
            "execution_id": execution_id,
            "render_job_id": render_job_id,
        }), encoding="utf-8")

    def test_missing_checkpoint_blocks(self):
        with self.assertRaisesRegex(CheckpointValidationError, "MISSING_EDIT_QA"):
            validate_edit_checkpoint(self.root, "execution-123")

    def test_checkpoint_from_another_execution_blocks(self):
        self.write_edit_qa(execution_id="old-execution")
        with self.assertRaisesRegex(CheckpointValidationError, "EXECUTION_ID_MISMATCH"):
            validate_edit_checkpoint(self.root, "execution-123")

    def test_checkpoint_for_another_render_job_blocks(self):
        self.write_edit_qa(render_job_id=999)
        with self.assertRaisesRegex(CheckpointValidationError, "RENDER_JOB_ID_MISMATCH"):
            validate_edit_checkpoint(self.root, "execution-123")

    def test_matching_checkpoint_passes(self):
        self.write_edit_qa()
        result = validate_edit_checkpoint(self.root, "execution-123")
        self.assertEqual(result["execution_id"], "execution-123")
        self.assertEqual(result["render_job_id"], 456)

    def test_checkpoint_without_identity_metadata_blocks(self):
        (self.root / "edit-qa.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        with self.assertRaisesRegex(CheckpointValidationError, "MISSING_CHECKPOINT_IDENTITY"):
            validate_edit_checkpoint(self.root, "execution-123")


if __name__ == "__main__":
    unittest.main()
