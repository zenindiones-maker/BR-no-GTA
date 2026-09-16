from pathlib import Path

path = Path("app/services/youtube_publication_readiness_service.py")
text = path.read_text(encoding="utf-8")
old = '''        if video.get("render_job_id") != render_job_id:\n            raise ValueError("Video/Goal render_job_id mismatch")\n\n'''
assert text.count(old) == 1, "expected obsolete Video.render_job_id readiness check"
text = text.replace(old, "")
path.write_text(text, encoding="utf-8")
