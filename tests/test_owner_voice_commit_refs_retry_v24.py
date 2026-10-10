"""Fast local Git-backed ledger recovery contracts. No network or owner data."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.services.owner_voice_audition_ledger_store import (
    OwnerVoiceAuditionGitLedgerStore, CasConflict, ALLOWED_LEDGER_REF,
)


OLD = "a" * 40
NEW = "b" * 40


class LedgerBackendTransientRecovery(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        root = Path(self.td.name)
        self.store = OwnerVoiceAuditionGitLedgerStore(
            repo_root=root,
            ssh_private_key_path=root / "fake-key",
            repository_ssh="git@github.com:zenindiones-maker/BR-no-GTA-audition-ledger.git",
        )

    def test_one_backend_failure_then_exact_remote_success(self):
        calls = []
        def fake_push(args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stderr="remote: fatal error in commit_refs", stdout="")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        with patch.object(self.store, "_remote_oid", side_effect=[OLD, OLD, NEW]), \
             patch("app.services.owner_voice_audition_ledger_store.subprocess.run", side_effect=fake_push), \
             patch("app.services.owner_voice_audition_ledger_store.time.sleep") as wait:
            self.assertEqual(
                self.store._push_candidate_bounded(expected_head_sha=OLD, candidate=NEW),
                NEW,
            )
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(cmd == ["git", "push", self.store.repository_ssh,
                                    f"{NEW}:{ALLOWED_LEDGER_REF}"] for cmd in calls))
        wait.assert_called_once_with(1.0)

    def test_persistent_backend_failure_fails_closed_after_three(self):
        pushes = []
        def fail(args, **kwargs):
            pushes.append(args)
            return SimpleNamespace(returncode=1,
                                   stderr="remote: fatal error in commit_refs", stdout="")
        with patch.object(self.store, "_remote_oid", side_effect=[OLD, OLD, OLD, OLD]), \
             patch("app.services.owner_voice_audition_ledger_store.subprocess.run", side_effect=fail), \
             patch("app.services.owner_voice_audition_ledger_store.time.sleep") as wait:
            with self.assertRaisesRegex(RuntimeError, "BACKEND_UNAVAILABLE"):
                self.store._push_candidate_bounded(expected_head_sha=OLD, candidate=NEW)
        self.assertEqual(len(pushes), 3)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [1.0, 3.0])
        self.assertTrue(all("--force" not in x for args in pushes for x in args))

    def test_remote_ref_change_prevents_second_write(self):
        calls = []
        def fail(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=1, stderr="fatal error in commit_refs", stdout="")
        with patch.object(self.store, "_remote_oid", side_effect=[OLD, "c"*40]), \
             patch("app.services.owner_voice_audition_ledger_store.subprocess.run", side_effect=fail), \
             patch("app.services.owner_voice_audition_ledger_store.time.sleep") as wait:
            with self.assertRaises(CasConflict):
                self.store._push_candidate_bounded(expected_head_sha=OLD, candidate=NEW)
        self.assertEqual(len(calls), 1)
        wait.assert_not_called()

    def test_ambiguous_exit_zero_needs_remote_readback(self):
        calls = []
        def fake(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        with patch.object(self.store, "_remote_oid", side_effect=[OLD, OLD]), \
             patch("app.services.owner_voice_audition_ledger_store.subprocess.run", side_effect=fake), \
             patch("app.services.owner_voice_audition_ledger_store.time.sleep") as wait:
            with self.assertRaisesRegex(RuntimeError, "READBACK_MISMATCH"):
                self.store._push_candidate_bounded(expected_head_sha=OLD, candidate=NEW)
        self.assertEqual(len(calls), 1)
        wait.assert_not_called()

    def test_invalid_oid_fails_before_network(self):
        with patch.object(self.store, "_remote_oid", side_effect=RuntimeError("network shouldn't be touched")):
            with self.assertRaises(ValueError):
                self.store._push_candidate_bounded(expected_head_sha=OLD, candidate="--force")

if __name__ == "__main__":
    unittest.main()
