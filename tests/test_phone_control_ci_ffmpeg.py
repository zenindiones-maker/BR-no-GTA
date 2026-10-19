"""A suíte canônica completa exige ffmpeg/ffprobe reais (probe acústico do dono,
integração de branding). O runner ubuntu-latest não os garante: instalar via apt
(gratuito, open source) antes da suíte, sem pular testes."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/phone-control-validation.yml"


def test_full_suite_job_installs_ffmpeg_before_running_tests():
    text = WORKFLOW.read_text(encoding="utf-8")
    install = text.find("sudo apt-get install -y --no-install-recommends ffmpeg")
    verify = text.find("ffprobe -version")
    suite = text.find(".venv/bin/python -m pytest -q tests/")
    assert install != -1 and verify != -1 and suite != -1
    assert install < verify < suite
    assert "--deselect" not in text and "-k " not in text
