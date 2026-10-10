import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.services.run001_script_to_screen_frame_evidence import collect_frame_evidence

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class FrameEvidenceTests(unittest.TestCase):
    def test_extract_real_frame_but_do_not_claim_semantic_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            master=root/"pilot.mp4"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=blue:s=320x180:r=30","-t","2","-c:v","libx264","-y",str(master)],check=True)
            edl={"schema":"BRScriptToScreenEDL/v1","shots":[{"segment_id":"s1","asset_id":"a1","start_ms":0,"end_ms":1000,"visual_purpose":"show city","evidence_ref":"claim-1"}]}
            result=collect_frame_evidence(edl,master,root/"frames")
            self.assertEqual(result["technical_extraction"],"PASS")
            self.assertEqual(result["semantic_alignment"],"PENDING_INDEPENDENT_REVIEW")
            self.assertFalse(result["release_authorized"])
            self.assertEqual(result["frames"][0]["frame_sha256"],hashlib.sha256(Path(result["frames"][0]["frame_path"]).read_bytes()).hexdigest())
    def test_reject_scene_outside_rendered_duration(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            master=root/"pilot.mp4"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=red:s=320x180:r=30","-t","1","-c:v","libx264","-y",str(master)],check=True)
            with self.assertRaises(ValueError):
                collect_frame_evidence({"schema":"BRScriptToScreenEDL/v1","shots":[{"start_ms":0,"end_ms":5000}]},master,root/"frames")

if __name__=="__main__":
    unittest.main()
