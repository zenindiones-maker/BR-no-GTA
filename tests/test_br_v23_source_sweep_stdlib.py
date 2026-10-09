"""Adversarial regression tests for read-only REA-scoped source inventory."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.audits.br_v23_source_sweep import (
    CRITICAL_REFERENCES, category, inventory, permitted_execution_host,
)


class SourceSweepTests(unittest.TestCase):
    def test_domain_inventory_labels_do_not_claim_ghidra(self):
        self.assertEqual("python_source", category("scripts/unit.py"))
        self.assertEqual("javascript_source", category("app/site/main.js"))
        self.assertEqual("native_managed_binary", category("bin/native.elf"))
        self.assertEqual("native_managed_binary", category("app/main.wasm"))
        self.assertEqual("model_weight_metadata_only", category("model.safetensors"))
        self.assertEqual("media_asset_metadata_only", category("ref.wav"))

    def test_control_device_denied_even_if_environment_is_spoofed(self):
        env = {
            "CODESPACES": "true",
            "CODESPACE_NAME": "br-v23-recovery-gxp67g5g7wphwxjw",
            "PREFIX": "/data/data/com.termux/files/usr",
        }
        self.assertFalse(permitted_execution_host(env, root=Path("/repo")))

    def test_wrong_codespace_is_denied(self):
        env = {"CODESPACES": "true", "CODESPACE_NAME": "other"}
        self.assertFalse(permitted_execution_host(env, root=Path("/repo")))

    def test_correct_codespace_host_only(self):
        env = {"CODESPACES": "true",
               "CODESPACE_NAME": "br-v23-recovery-gxp67g5g7wphwxjw"}
        self.assertTrue(permitted_execution_host(env, root=Path("/workspaces/BR-no-GTA")))

    def test_arbitrary_ci_workflow_cannot_trigger_sweep(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_WORKFLOW": "Other Workflow"}
        self.assertFalse(permitted_execution_host(env, root=Path("/repo")))
        env["GITHUB_WORKFLOW"] = "BR V23 Isolated Owner Voice Contracts"
        self.assertTrue(permitted_execution_host(env, root=Path("/repo")))

    def test_complete_fixture_is_static_only_and_never_runs_voice_or_ghidra(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in CRITICAL_REFERENCES:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(
                    "docs/governance/a15-control-plane-only.md"
                    if name == "AGENTS.md" else "# source fixture\n",
                    encoding="utf-8",
                )
            owned_python = root / "safe.py"
            owned_python.write_text("answer=42\n")
            private = root / "private.wav"
            private.write_bytes(b"PRIVATE_MEDIA_MUST_NOT_BE_DECODED")
            bad = root / "bad.py"
            bad.write_bytes(b"def broken(:\n")
            paths = sorted([*CRITICAL_REFERENCES, "safe.py", "private.wav", "bad.py"])
            with patch("scripts.audits.br_v23_source_sweep._checked_git_paths",
                       return_value=("f" * 40, paths)):
                result = inventory(root)
            self.assertEqual("PASS", result["critical_integrity"])
            self.assertEqual(1, result["anomalies"]["python_ast_parse_error"])
            self.assertEqual(len(paths), result["tracked_count"])
            self.assertFalse(result["ghidra_executed"])
            self.assertFalse(result["owner_voice_accessed"])
            self.assertEqual("STATIC_INVENTORY_ONLY_NOT_FULL_REVERSE_ENGINEERING",
                             result["conclusion"])

    def test_missing_canonical_reference_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "AGENTS.md").write_text(
                "docs/governance/a15-control-plane-only.md", encoding="utf-8",
            )
            with patch("scripts.audits.br_v23_source_sweep._checked_git_paths",
                       return_value=("f" * 40, ["AGENTS.md"])):
                result = inventory(root)
            self.assertEqual("FAIL", result["critical_integrity"])
            self.assertGreater(result["anomalies"]["critical_reference_missing"], 0)


if __name__ == "__main__":
    unittest.main()
