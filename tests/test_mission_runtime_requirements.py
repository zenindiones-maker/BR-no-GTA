from scripts.mission_runtime_requirements import classify_plan_runtime_requirements


def _plan(*, tools):
    return {
        "authority": "DEEPSEEK_HARNESS",
        "collaboration_plan": {
            "tasks": [
                {
                    "task_id": "investigate",
                    "capability_id": "agent-office.deterministic.readonly-analysis",
                    "selected_executor_binding": (
                        "app.services.agent_office_harness_service."
                        "execute_authorized_agent_office_specialist"
                    ),
                    "allowed_tools": list(tools),
                }
            ]
        },
    }


def test_runtime_requirements_do_not_make_codex_or_tuxevil_global_prerequisites():
    report = classify_plan_runtime_requirements(_plan(tools=("git",)))
    assert report["codex_required"] is False
    assert report["tuxevil_required"] is False
    assert report["global_provider_prerequisite"] is False
    assert report["executor_bootstrap_mode"] == "LAZY_SELECTED_TASK_TOOLS"


def test_runtime_requirements_bootstrap_codex_only_when_selected_task_allows_it():
    report = classify_plan_runtime_requirements(
        _plan(tools=("git", "python", "codex"))
    )
    assert report["codex_required"] is True
    assert report["tuxevil_required"] is False
    assert report["tool_owners"]["codex"] == ["investigate"]
