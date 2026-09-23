from scripts.mission_runtime_requirements import classify_plan_runtime_requirements


def _plan(*, tools):
    return {
        "authority": "DEEPSEEK_HARNESS",
        "collaboration_plan": {
            "tasks": [
                {
                    "task_id": "investigate",
                    "capability_id": "agent-office.deterministic-analysis",
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
    assert report["semantic_provider_required"] is False
    assert report["executor_bootstrap_mode"] == "LAZY_SELECTED_TASK_TOOLS"


def test_runtime_requirements_bootstrap_codex_only_when_selected_task_allows_it():
    report = classify_plan_runtime_requirements(
        _plan(tools=("git", "python", "codex"))
    )
    assert report["codex_required"] is True
    assert report["tuxevil_required"] is False
    assert report["tool_owners"]["codex"] == ["investigate"]



def test_runtime_requirements_restore_addy_source_without_codex_bootstrap():
    plan = {
        "authority": "DEEPSEEK_HARNESS",
        "collaboration_plan": {
            "tasks": [
                {
                    "task_id": "profile",
                    "capability_id": "addy:planning-and-task-breakdown",
                    "selected_executor_binding": (
                        "app.services.addy_harness_service."
                        "execute_authorized_addy_skill"
                    ),
                    "allowed_tools": ["git", "python"],
                }
            ]
        },
    }
    report = classify_plan_runtime_requirements(plan)
    assert report["addy_source_required"] is True
    assert report["semantic_provider_required"] is True
    assert report["semantic_provider_task_ids"] == ["profile"]
    assert report["codex_required"] is False
    assert report["tuxevil_required"] is False
    assert (
        "app.services.addy_harness_service.execute_authorized_addy_skill"
        in report["selected_executor_bindings"]
    )


def test_dynamic_workflow_bootstraps_addy_only_when_task_envelope_requires_it():
    from pathlib import Path

    source = Path(
        ".github/workflows/dynamic-system-improvement.yml"
    ).read_text(encoding="utf-8")
    assert "steps.runtime.outputs.addy_source_required == 'true'" in source
    assert "bash scripts/agent-tooling/bootstrap.sh addy" in source
    assert "CODEX_BOOTSTRAP_FOR_ADDY_SOURCE_ONLY=NO" in source
