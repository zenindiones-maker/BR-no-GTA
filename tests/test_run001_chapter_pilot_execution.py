import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.run001_chapter_pilot_execution import main

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class ChapterPilotExecutionTests(unittest.TestCase):
    def test_end_to_end_pilot_and_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            image=root/"shot.png"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=blue:s=320x180","-frames:v","1","-y",str(image)],check=True)
            edl={"schema":"BRScriptToScreenEDL/v1","status":"READY_FOR_RENDERER_ADAPTATION","coverage_sha256":"a"*64,"shots":[{"segment_id":"s1","asset_id":"a1","media_path":str(image),"media_sha256":hashlib.sha256(image.read_bytes()).hexdigest(),"start_ms":0,"end_ms":1000,"visual_purpose":"test shot","evidence_ref":"test-only"}]}
            contract=root/"edl.json"
            contract.write_text(json.dumps(edl))
            with patch("sys.argv",["pilot","--edl",str(contract),"--out-dir",str(root/"out")]):
                self.assertEqual(main(),0)
            receipt=json.loads((root/"out/pilot-receipt.json").read_text())
            evidence=json.loads((root/"out/frame-evidence.json").read_text())
            self.assertFalse(receipt["release_authorized"])
            self.assertEqual(evidence["semantic_alignment"],"PENDING_INDEPENDENT_REVIEW")
            self.assertEqual(len(evidence["frames"]),1)

if __name__=="__main__":
    unittest.main()
