from app.services.harness_review_independence_service import evaluate_review_independence

def principal(**overrides):
    base=dict(task_id="proposal",worker_id="worker:addy:constraint-driven-development",agent_instance_id="P",authorization_id="auth-p",session_ref="artifact:session-p",execution_kind="CAPABILITY_WORKER",functional_role="PROPOSAL",capability_id="addy:constraint-driven-development",content_sha256="p"*64,provider_id="nvidia",model_id="m",authority="NONE")
    base.update(overrides);return base

def review(**overrides):
    base=dict(task_id="review",worker_id="worker:addy:code-review-and-quality",agent_instance_id="R",authorization_id="auth-r",session_ref="artifact:session-r",execution_kind="INDEPENDENT_REVIEWER",functional_role="REVIEW",capability_id="addy:code-review-and-quality",content_sha256="r"*64,provider_id="nvidia",model_id="m",authority="NONE")
    base.update(overrides);return base

def decide(a=None,b=None,ref="artifact:task-result",sha="a"*64,bound_ref="artifact:task-result",bound_sha="a"*64,ro=True,support=True):
    return evaluate_review_independence(reviewed_execution_principal=a if a is not None else principal(),reviewer_execution_principal=b if b is not None else review(),reviewed_task_result_ref=ref,reviewed_task_result_content_sha256=sha,bound_task_result_ref=bound_ref,bound_task_result_sha256=bound_sha,reviewed_execution_principal_ref="artifact:principal-p",reviewer_execution_principal_ref="artifact:principal-r",reviewer_read_only=ro,reviewer_supports_review=support)

def test_addy_same_logical_family_distinct_execution_principals_pass():
    a=principal(agent_id="addy-agent-skills");b=review(agent_id="addy-agent-skills")
    e=decide(a,b)
    assert a["agent_id"]==b["agent_id"]
    assert e.decision=="PASS"
    assert e.checks["distinct_worker"] and e.checks["distinct_agent_instance"] and e.checks["distinct_authorization"] and e.checks["distinct_session"]
    assert e.provider_diversity=="SAME_PROVIDER"
    assert e.model_diversity=="SAME_MODEL"

def test_same_task_rejected(): assert decide(b=review(task_id="proposal")).decision=="FAIL"
def test_same_worker_rejected(): assert decide(b=review(worker_id=principal()["worker_id"])).decision=="FAIL"
def test_same_agent_instance_rejected(): assert decide(b=review(agent_instance_id="P")).decision=="FAIL"
def test_same_authorization_rejected(): assert decide(b=review(authorization_id="auth-p")).decision=="FAIL"
def test_same_session_rejected(): assert decide(b=review(session_ref="artifact:session-p")).decision=="FAIL"
def test_not_read_only_rejected(): assert decide(ro=False).decision=="FAIL"
def test_non_review_execution_kind_rejected(): assert decide(b=review(execution_kind="CAPABILITY_WORKER")).decision=="FAIL"
def test_without_can_review_rejected(): assert decide(support=False).decision=="FAIL"
def test_wrong_task_result_rejected(): assert decide(bound_ref="artifact:other").decision=="FAIL"
def test_tampered_task_result_rejected(): assert decide(bound_sha="b"*64).decision=="FAIL"
def test_authority_bearing_reviewer_rejected(): assert decide(b=review(authority="MISSION_AUTHORITY")).decision=="FAIL"
def test_hermes_reviewer_rejected(): assert decide(b=review(capability_id="collaboration.hermes.execute")).decision=="FAIL"

def test_missing_execution_principal_rejected():
    import pytest
    with pytest.raises(PermissionError,match="MISSING_EXECUTION_PRINCIPAL_REJECTED"):
        decide(a={})
