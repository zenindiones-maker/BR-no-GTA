"""Adversarial source-of-truth governance tests (stdlib, real temporary Git repos)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.source_of_truth_guard import validate, GovernanceError

def git(root,*args):
    p=subprocess.run(["git",*args],cwd=root,text=True,capture_output=True,check=True)
    return p.stdout.strip()

class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        git(self.root,"init","-q")
        git(self.root,"config","user.email","governance@example.invalid")
        git(self.root,"config","user.name","test")
        (self.root/"AGENTS.md").write_text("Required: `docs/governance/source-of-truth.md`\n")
        (self.root/"docs/governance").mkdir(parents=True)
        (self.root/"docs/governance/source-of-truth.md").write_text("# Authority\n")
        (self.root/"config").mkdir()
        self.policy={
            "schema":"BRSourceOfTruthPolicy/v1",
            "authority_doc":"docs/governance/source-of-truth.md",
            "required_paths":["AGENTS.md","docs/governance/source-of-truth.md"],
            "retired_branches":["work/legacy-v1"],
            "tombstones":[],
            "evidence_files":[],
        }
        self.write_policy()
        git(self.root,"add",".")
        git(self.root,"commit","-qm","baseline")
        self.base=git(self.root,"rev-parse","HEAD")
    def write_policy(self):
        (self.root/"config/source-of-truth-policy.json").write_text(json.dumps(self.policy))
    def check(self,**kw):
        return validate(self.root,expected_sha=git(self.root,"rev-parse","HEAD"),expected_tree=git(self.root,"rev-parse","HEAD^{tree}"),**kw)
    def test_clean_baseline_passes(self):
        self.assertEqual("PASS",self.check()["status"])
    def test_wrong_commit_or_tree_rejected(self):
        with self.assertRaisesRegex(GovernanceError,"HEAD_MISMATCH"):
            validate(self.root,expected_sha="0"*40,expected_tree=git(self.root,"rev-parse","HEAD^{tree}"))
        with self.assertRaisesRegex(GovernanceError,"TREE_MISMATCH"):
            validate(self.root,expected_sha=self.base,expected_tree="f"*40)
    def test_dirty_worktree_blocks_without_discarding_changes(self):
        (self.root/"AGENTS.md").write_text("uncommitted")
        with self.assertRaisesRegex(GovernanceError,"DIRTY_WORKTREE"):
            self.check()
        self.assertEqual("uncommitted",(self.root/"AGENTS.md").read_text())
    def test_missing_active_required_reference_fails(self):
        self.policy["required_paths"].append("app/services/deleted.py")
        self.write_policy();git(self.root,"add",".");git(self.root,"commit","-qm","dangling")
        with self.assertRaisesRegex(GovernanceError,"MISSING_ACTIVE_REFERENCE"):
            self.check()
    def test_retired_branch_receipt_rejected(self):
        (self.root/"evidence").mkdir()
        (self.root/"evidence/a.json").write_text(json.dumps({"source_branch":"work/legacy-v1","source_sha":self.base,"source_tree":git(self.root,"rev-parse","HEAD^{tree}")}))
        self.policy["evidence_files"]=["evidence/a.json"]
        self.write_policy();git(self.root,"add",".");git(self.root,"commit","-qm","stale receipt")
        with self.assertRaisesRegex(GovernanceError,"RETIRED_BRANCH_EVIDENCE"):
            self.check()
    def test_wrong_receipt_sha_fails(self):
        (self.root/"evidence").mkdir()
        (self.root/"evidence/a.json").write_text(json.dumps({"source_branch":"work/valid","source_sha":"0"*40,"source_tree":"f"*40}))
        self.policy["evidence_files"]=["evidence/a.json"]
        self.write_policy();git(self.root,"add",".");git(self.root,"commit","-qm","wrong receipt")
        with self.assertRaisesRegex(GovernanceError,"EVIDENCE_SHA_MISMATCH"):
            self.check()
    def test_protected_tombstone_restoration_rejected_even_with_local_approval_claim(self):
        (self.root/"deleted.py").write_text("historical")
        git(self.root,"add",".");git(self.root,"commit","-qm","historical")
        git(self.root,"rm","-q","deleted.py")
        git(self.root,"commit","-qm","intentional deletion")
        baseline=git(self.root,"rev-parse","HEAD")
        self.policy["tombstones"]=[{"path":"deleted.py","deleted_at":baseline,"reason":"explicit retirement"}]
        self.write_policy();git(self.root,"add",".");git(self.root,"commit","-qm","register tombstone")
        (self.root/"deleted.py").write_text("obsolete implementation")
        git(self.root,"add",".");git(self.root,"commit","-qm","unauthorized restore")
        with self.assertRaisesRegex(GovernanceError,"TOMBSTONE_RESTORED"):
            self.check()
    def test_no_fake_exception_from_repository_receipt(self):
        (self.root/"obsolete.py").write_text("old")
        git(self.root,"add",".");git(self.root,"commit","-qm","old")
        git(self.root,"rm","-q","obsolete.py");git(self.root,"commit","-qm","removed")
        parent=git(self.root,"rev-parse","HEAD")
        self.policy["tombstones"]=[{"path":"obsolete.py","deleted_at":parent,"reason":"obsolete"}]
        self.write_policy();git(self.root,"add",".");git(self.root,"commit","-qm","tombstone")
        (self.root/"obsolete.py").write_text("recreated")
        (self.root/"approval.json").write_text('{"approved":true,"tests_passed":true}')
        git(self.root,"add",".");git(self.root,"commit","-qm","local fake approval")
        with self.assertRaisesRegex(GovernanceError,"TOMBSTONE_RESTORED"):
            self.check()

if __name__=="__main__": unittest.main()
