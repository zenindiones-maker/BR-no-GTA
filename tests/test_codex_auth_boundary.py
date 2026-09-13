from pathlib import Path
import subprocess

from app.services.codex_addy_capability_executor import execute_codex_addy_capability
from app.services.harness_capability_service import (
    CapabilityAuthorization,
    CapabilityDefinition,
    execute_capability,
)


def capability():
    return CapabilityDefinition(
        capability_id="addy:code-review-and-quality",
        provider="addy-agent-skills",
        execution_kind="codex_native_skill",
        allowed_actions=("DEVELOPMENT",),
        tags=("code", "review", "quality"),
    )


def repo(tmp_path: Path):
    root=tmp_path/'repo'; root.mkdir()
    subprocess.run(['git','init'],cwd=root,check=True,capture_output=True)
    (root/'sample.py').write_text('VALUE = 1\n')
    subprocess.run(['git','add','sample.py'],cwd=root,check=True)
    return root


def auth():
    return CapabilityAuthorization('deepseek_harness','DEVELOPMENT','decision-canary','execution-canary')


def test_missing_codex_auth_is_blocked_before_model_turn(tmp_path):
    root=repo(tmp_path); calls=[]
    def runner(command, **kwargs):
        calls.append(command)
        assert command == ['codex','login','status']
        return subprocess.CompletedProcess(command,1,stdout='',stderr='sensitive detail')
    evidence=execute_capability(
        capability_id='addy:code-review-and-quality', authorization=auth(),
        payload={'task':'Review sample.py without modifying it.'},
        executor=lambda c,p: execute_codex_addy_capability(c,p,runner=runner,repository_root=root),
    )
    assert calls == [['codex','login','status']]
    assert evidence.status == 'BLOCKED'
    assert evidence.active is False
    assert evidence.result == {'stage':'authentication','error':'Codex authentication is not available in the ephemeral runner'}
    assert evidence.boundary == 'Codex authentication prerequisite missing; no model turn started'
    assert 'sensitive' not in str(evidence.to_dict())


def test_authenticated_executor_invokes_exactly_one_selected_skill(tmp_path):
    root=repo(tmp_path); calls=[]
    def runner(command, **kwargs):
        calls.append(command)
        if command == ['codex','login','status']:
            return subprocess.CompletedProcess(command,0,stdout='logged in',stderr='')
        assert command[:2] == ['codex','exec']
        assert '@code-review-and-quality' in command[-1]
        assert '@using-agent-skills' not in command[-1]
        return subprocess.CompletedProcess(command,0,stdout='{"item":{"type":"agent_message","text":"bounded review"}}\n',stderr='')
    evidence=execute_capability(
        capability_id='addy:code-review-and-quality', authorization=auth(),
        payload={'task':'Review sample.py without modifying it.'},
        executor=lambda c,p: execute_codex_addy_capability(c,p,runner=runner,repository_root=root),
    )
    assert len(calls) == 2
    assert evidence.status == 'EXECUTED'
    assert evidence.active is True
    assert evidence.result['skill'] == 'code-review-and-quality'
    assert not (root/'temporary-change.txt').exists()
