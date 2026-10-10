"""Negative and integrity tests for the inert ARTEX source quarantine.

Tests exercise only local files; they are not ARTEX runtime or E2E evidence.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import tarfile
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


    def test_tree_oid_matches_git_write_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repository = base / "upstream"
            repository.mkdir()
            (repository / "nested").mkdir()
            (repository / "nested" / "file.txt").write_text("hello")
            (repository / "build.sh").write_text("#!/bin/sh\nexit 0\n")
            (repository / "build.sh").chmod(0o755)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "add", "--all"],
                check=True,
            )
            actual = subprocess.check_output(
                ["git", "-C", str(repository), "write-tree"],
                text=True,
            ).strip()
            payload = base / "payload"
            payload.mkdir()
            (payload / "nested").mkdir()
            (payload / "nested" / "file.txt").write_text("hello")
            (payload / "build.sh").write_text("#!/bin/sh\nexit 0\n")
            # The historical staging loses executable bits: reconstruct pin.
            self.assertEqual(artex._git_tree_oid(payload), actual)

    def test_git_archive_crlf_export_matches_pinned_git_tree(self):
        """Replicate the upstream .gitattributes and archive workflow exactly."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "fixture"
            repo.mkdir()
            (repo / ".gitattributes").write_text(
                "*.bat text eol=crlf\n*.sh  text eol=lf\n",
                encoding="utf-8",
            )
            (repo / "start.bat").write_bytes(b"@echo off\r\necho test\r\n")
            (repo / "readme.txt").write_text("research-only\n")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=Test",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "pinned"],
                check=True,
            )
            expected = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
                text=True,
            ).strip()
            archive = subprocess.check_output(
                ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
            )
            payload = root / "payload"
            payload.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                for member in bundle:
                    if member.isfile():
                        target = payload / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        stream = bundle.extractfile(member)
                        self.assertIsNotNone(stream)
                        target.write_bytes(stream.read())
            self.assertIn(b"\r\n", (payload / "start.bat").read_bytes())
            committed_blob = subprocess.check_output(
                ["git", "-C", str(repo), "show", "HEAD:start.bat"],
            )
            self.assertNotIn(b"\r\n", committed_blob)
            self.assertEqual(artex._git_tree_oid(payload), expected)
            (payload / "start.bat").write_bytes(b"@echo off\r\necho hacked\r\n")
            self.assertNotEqual(artex._git_tree_oid(payload), expected)

    def test_receipt_cannot_mask_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src.txt"
            source.write_text("original")
            original_tree = artex._git_tree_oid(root)
            with patch.object(artex, "TREE", original_tree):
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
                # Attacker updates the self-authored receipt: must still fail
                # because the immutable Git tree is independently pinned.
                new_count, new_size, new_digest = artex._manifest(root)
                (root / artex.RECEIPT).write_text(json.dumps({
                    "repository": artex.SOURCE, "commit": artex.REV,
                    "tree": artex.TREE, "file_count": new_count,
                    "byte_count": new_size, "manifest_sha256": new_digest,
                    "runtime_enabled": False,
                }))
                with self.assertRaises(artex.Blocked):
                    artex._verify(root)

    def test_additional_untracked_file_changes_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("data")
            original = artex._git_tree_oid(root)
            (root / "extra.txt").write_text("unexpected")
            self.assertNotEqual(artex._git_tree_oid(root), original)

    def test_unexpected_executable_source_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.txt"
            source.write_text("ordinary")
            source.chmod(0o755)
            with self.assertRaises(artex.Blocked):
                artex._git_tree_oid(root)

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
