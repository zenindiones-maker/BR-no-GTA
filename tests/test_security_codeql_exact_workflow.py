from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_security_codeql_exact_runs_on_security_staging_and_canonical():
    path = ROOT / ".github" / "workflows" / "security-codeql-exact.yml"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert '      - "staging/security-*"' in text
    assert "      - work/gate6f-analytics-learning" in text
    assert "persist-credentials: false" in text
    assert "security-events: write" not in text
    assert "github/codeql-action/init@" in text
    assert "github/codeql-action/analyze@" in text
    assert "security-extended" in text
    assert "upload: false" in text
    assert "output: codeql-results" in text
    assert "Enforce no HIGH or CRITICAL CodeQL findings" in text

def test_ci_runs_full_checkpoint_on_security_staging():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert '      - "staging/security-*"' in text
    assert 'ref_name.startswith("staging/security-")' in text


def test_codeql_gate_resolves_security_severity_from_rule_descriptor():
    text = (ROOT / ".github" / "workflows" / "security-codeql-exact.yml").read_text(encoding="utf-8")
    assert 'driver.get("rules")' in text
    assert 'rule_index = result.get("ruleIndex")' in text
    assert 'result.get("ruleId")' in text
    assert 'rule.get("properties") or {}' in text
    assert 'security-severity' in text
