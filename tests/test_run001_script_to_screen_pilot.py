import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.run001_script_to_screen_pilot import render_pilot

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class PilotRenderTests(unittest.TestCase):
    def test_real_pilot_renders_and_is_never_releasable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            image=root/"frame.png"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=blue:s=320x180:r=30","-frames:v","1","-y",str(image)],check=True)
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            edl={"schema":"BRScriptToScreenEDL/v1","status":"READY_FOR_RENDERER_ADAPTATION","coverage_sha256":"a"*64,"shots":[{"segment_id":"s1","asset_id":"a1","media_path":str(image),"media_sha256":digest,"start_ms":0,"end_ms":1000,"visual_purpose":"fixture","evidence_ref":"test"}]}
            result=render_pilot(edl,root/"pilot.mp4")
            self.assertEqual(result["status"],"PASS")
            self.assertFalse(result["release_authorized"])
            self.assertFalse(result["narration_present"])
            self.assertTrue((root/"pilot.mp4").stat().st_size>0)
    def test_gap_in_timeline_fails(self):
        with self.assertRaises(ValueError):
            render_pilot({"schema":"BRScriptToScreenEDL/v1","status":"READY_FOR_RENDERER_ADAPTATION","shots":[{"start_ms":500,"end_ms":1000}]},Path("/tmp/should-not-create.mp4"))

if __name__=="__main__":
    unittest.main()
