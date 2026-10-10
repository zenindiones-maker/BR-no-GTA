"""Negative and integrity tests for the inert ARTEX source quarantine.

Tests exercise only local files; they are not ARTEX runtime or E2E evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "br_artex_source_quarantine.py"
spec = importlib.util.spec_from_file_location("br_artex_source_quarantine", MODULE_PATH)
assert spec and spec.loader
artex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artex)


class ArtexQuarantineTests(unittest.TestCase):
    def test_commit_and_tree_are_full_sha1_pins(self):
        self.assertEqual(len(artex.REV), 40)
        self.assertEqual(len(artex.TREE), 40)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in artex.REV))
        self.assertTrue(all(ch in "0123456789abcdef" for ch in artex.TREE))

    def test_unapproved_environment_is_rejected_before_git(self):
        with patch.dict(os.environ, {"CODESPACES": "false"}, clear=False):
            with self.assertRaises(artex.Blocked):
                artex._guard()

    def test_wrong_codespace_is_rejected_before_git(self):
        with patch.dict(os.environ, {"CODESPACES": "true", "CODESPACE_NAME": "unauthorized"}, clear=False):
            with self.assertRaises(artex.Blocked):
                artex._guard()

    def test_manifest_excludes_only_root_receipt_not_nested_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            nested = root / "dir"
            nested.mkdir()
            (nested / artex.RECEIPT).write_text("nested content", encoding="utf-8")
            (root / artex.RECEIPT).write_text("root receipt", encoding="utf-8")
            count, total, digest = artex._manifest(root)
            self.assertEqual(count, 2)
            self.assertEqual(total, len("hello") + len("nested content"))
            self.assertEqual(len(digest), 64)

    def test_manifest_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source.txt").write_text("data")
            (root / "link.txt").symlink_to(root / "source.txt")
            with self.assertRaises(artex.Blocked):
                artex._manifest(root)

    def test_receipt_cannot_mask_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src.txt"
            source.write_text("original")
            count, size, digest = artex._manifest(root)
            (root / artex.RECEIPT).write_text(json.dumps({
                "repository": artex.SOURCE, "commit": artex.REV,
                "tree": artex.TREE, "file_count": count,
                "byte_count": size, "manifest_sha256": digest,
                "runtime_enabled": False,
            }))
            with patch("builtins.print"):
                artex._verify(root)
            source.write_text("tampered")
            with self.assertRaises(artex.Blocked):
                artex._verify(root)

    def test_runtime_enabled_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            count, size, digest = artex._manifest(root)
            (root / artex.RECEIPT).write_text(json.dumps({
                "repository": artex.SOURCE, "commit": artex.REV,
                "tree": artex.TREE, "file_count": count,
                "byte_count": size, "manifest_sha256": digest,
                "runtime_enabled": True,
            }))
            with self.assertRaises(artex.Blocked):
                artex._verify(root)


if __name__ == "__main__":
    unittest.main()
