from pathlib import Path

path = Path("app/services/youtube_publication_readiness_service.py")
text = path.read_text(encoding="utf-8")
old = '''        if video.get("render_job_id") != render_job_id:\n            raise ValueError("Video/Goal render_job_id mismatch")\n\n'''
assert text.count(old) == 1, "expected obsolete Video.render_job_id readiness check"
text = text.replace(old, "")
path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_youtube_publication_readiness_service.py")
tests = test_path.read_text(encoding="utf-8")
old = "from app.database.connection import get_connection\n"
new = (
    "from app.database.connection import get_connection\n"
    "from app.database.youtube_cloud_execution_repository import get_youtube_cloud_execution\n"
)
assert tests.count(old) == 1, "expected readiness test connection import"
tests = tests.replace(old, new)
old = '    assert json.loads(after["cloud_execution"]) == cloud_execution\n'
new = '    assert get_youtube_cloud_execution(publication_id) == cloud_execution\n'
assert tests.count(old) == 1, "expected obsolete readiness cloud_execution assertion"
tests = tests.replace(old, new)
test_path.write_text(tests, encoding="utf-8")
