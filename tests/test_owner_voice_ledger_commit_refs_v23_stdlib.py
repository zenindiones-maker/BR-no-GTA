"""Regression: commit_refs is not necessarily a non-fast-forward conflict."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.owner_voice_audition_ledger_store import OwnerVoiceAuditionGitLedgerStore


class CommitRefsRegression(unittest.TestCase):
    def test_git_server_commit_refs_failure_bounded_for_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "dummy-key"
            key.write_text("fixture")
            store = OwnerVoiceAuditionGitLedgerStore(
                repo_root=root,
                repository_ssh=str(root / "remote.git"),
                ssh_private_key_path=key,
            )
            old, new = "1" * 40, "2" * 40
            remote = iter([old, old, old])
            pushes = []

            def rejected(*args, **kwargs):
                pushes.append(args[0])
                return SimpleNamespace(
                    returncode=1,
                    stderr="remote: fatal error in commit_refs",
                    stdout="",
                )

            with (
                patch.object(store, "_remote_oid", side_effect=lambda: next(remote)),
                patch("app.services.owner_voice_audition_ledger_store.subprocess.run", side_effect=rejected),
            ):
                with self.assertRaisesRegex(RuntimeError, "LEDGER_TRANSIENT_COMMIT_REFS_EXHAUSTED"):
                    store._push_candidate_bounded(expected_head_sha=old, candidate=new)

            self.assertEqual(2, len(pushes))
            self.assertEqual(pushes[0], pushes[1])
            self.assertFalse(any("--force" in str(x) for x in pushes))


if __name__ == "__main__":
    unittest.main()
