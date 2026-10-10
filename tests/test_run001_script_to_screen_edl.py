import hashlib
import tempfile
import unittest
from pathlib import Path
from app.services.run001_script_to_screen_edl import build_edit_decision_list
from app.services.run001_script_to_screen_contract import ScreenContractError

class ScriptToScreenEDLTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"frame.bin"
        self.path.write_bytes(b"real-asset-fixture")
        self.digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.script={"segments":[{"id":"s1","text":"Vice City","start_ms":0,"end_ms":2000}]}
        self.plan={"shots":[{"segment_id":"s1","asset_id":"a1","source_ref":"official","evidence_ref":"claim-1","visual_purpose":"show city","rights_status":"CLEARED","start_ms":0,"end_ms":2000}]}
        self.assets={"a1":{"path":str(self.path),"sha256":self.digest,"source_ref":"official","rights_status":"CLEARED"}}
    def test_verified_asset_yields_non_authorizing_edl(self):
        r=build_edit_decision_list(self.script,self.plan,self.assets)
        self.assertEqual(r["shots"][0]["media_sha256"],self.digest)
        self.assertFalse(r["render_authorized"])
        self.assertEqual(r["semantic_qa"],"PENDING_RENDERED_FRAME_REVIEW")
    def test_video_in_point_is_preserved(self):
        self.assets["a1"]["media_kind"]="video"
        self.plan["shots"][0]["source_in_ms"]=250
        r=build_edit_decision_list(self.script,self.plan,self.assets)
        self.assertEqual(r["shots"][0]["source_in_ms"],250)
        self.assertEqual(r["shots"][0]["media_kind"],"video")
    def test_video_without_in_point_fails(self):
        self.assets["a1"]["media_kind"]="video"
        with self.assertRaises(ScreenContractError):
            build_edit_decision_list(self.script,self.plan,self.assets)
    def test_missing_media_rejected(self):
        self.path.unlink()
        with self.assertRaises(ScreenContractError):
            build_edit_decision_list(self.script,self.plan,self.assets)
    def test_modified_media_rejected(self):
        self.path.write_bytes(b"tampered")
        with self.assertRaises(ScreenContractError):
            build_edit_decision_list(self.script,self.plan,self.assets)
    def test_source_mismatch_rejected(self):
        self.assets["a1"]["source_ref"]="unknown"
        with self.assertRaises(ScreenContractError):
            build_edit_decision_list(self.script,self.plan,self.assets)
    def test_uncleared_media_rejected(self):
        self.assets["a1"]["rights_status"]="UNKNOWN"
        with self.assertRaises(ScreenContractError):
            build_edit_decision_list(self.script,self.plan,self.assets)

if __name__=="__main__":
    unittest.main()
