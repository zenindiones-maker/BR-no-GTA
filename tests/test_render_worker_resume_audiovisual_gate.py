from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/render-worker.yml"


def test_resumed_final_qa_requires_audiovisual_pass():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Validate QA-passed render contract")
    end = text.index("- name: Checkpoint QA-passed render before external review", start)
    resumed_gate = text[start:end]

    assert 'audiovisual=json.loads((root/"audiovisual-qa.json").read_text(encoding="utf-8"))' in resumed_gate
    assert 'assert audiovisual.get("status")=="PASS", audiovisual' in resumed_gate
