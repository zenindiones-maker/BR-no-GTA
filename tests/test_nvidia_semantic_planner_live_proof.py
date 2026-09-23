import json

from scripts.nvidia_semantic_planner_live_proof import _validate_response


def test_malformed_semantic_output_preserves_parse_failure_stage():
    context = {"resource_bounds": {"max_tasks_per_mission": 4}}
    result = _validate_response('{"g":"x",', context)
    assert result["PARSE_STARTED"] is True
    assert result["STRUCTURED_OUTPUT_VALID"] is False
    assert result["SCHEMA_VALID"] is False
    assert result["MISSION_PROPOSAL_SCHEMA_VALID"] is False
    assert result["HARNESS_VALIDATION_PASS"] is False
    assert result["PARSE_ERROR"].startswith("JSONDecodeError:")
    assert result["OUTPUT_FAILURE_CLASS"] == "F_MALFORMED_SEMANTIC_JSON"


def test_non_object_semantic_output_is_parse_failure_not_provider_failure():
    context = {"resource_bounds": {"max_tasks_per_mission": 4}}
    result = _validate_response(json.dumps(["not", "an", "object"]), context)
    assert result["PARSE_STARTED"] is True
    assert result["STRUCTURED_OUTPUT_VALID"] is False
    assert result["PARSE_ERROR"].startswith("ValueError:")
    assert result["HARNESS_VALIDATION_ERRORS"] == []


def test_compact_wire_format_is_expanded_before_schema_validation(monkeypatch):
    compact = {
        "g": "improve semantic planner",
        "a": [],
        "o": ["measure latency"],
        "t": [
            {
                "id": "measure",
                "obj": "measure current latency",
                "cls": "PERFORMANCE",
                "need": "deterministic performance measurement",
                "caps": [],
                "dep": [],
                "out": "latency evidence",
                "ok": ["latency measured"],
                "risk": "RO",
                "act": "D",
            }
        ],
        "why": "measure before mutation",
        "ctx": [],
        "u": 0.2,
        "ask": False,
        "q": None,
        "mem": [],
        "reuse": [],
        "avoid": [],
    }

    monkeypatch.setattr(
        "scripts.nvidia_semantic_planner_live_proof."
        "select_capability_for_requirement",
        lambda requirement, context, used: (
            "agent-office.deterministic.readonly-analysis",
            {},
            (),
            {},
        ),
    )
    result = _validate_response(
        json.dumps(compact),
        {"resource_bounds": {"max_tasks_per_mission": 4}},
    )
    assert result["WIRE_FORMAT_DETECTED"] == "COMPACT"
    assert "t" in result["RAW_TOP_LEVEL_KEYS"]
    assert result["PARSE_ERROR"] is None
    assert result["STRUCTURED_OUTPUT_VALID"] is True
    assert result["MISSION_PROPOSAL_SCHEMA_VALID"] is True
    assert result["HARNESS_VALIDATION_PASS"] is True


def test_validation_reports_failed_requirement_for_downstream_selection(monkeypatch):
    compact = {
        "g": "improve planner",
        "a": [],
        "o": ["measure"],
        "t": [{
            "id": "measure",
            "obj": "measure planner",
            "cls": "DEVELOPMENT",
            "need": "profile semantic planner",
            "caps": [],
            "dep": [],
            "out": "profile",
            "ok": ["profile captured"],
            "risk": "RO",
            "act": "D"
        }],
        "why": "measure",
        "ctx": [],
        "u": 0.2,
        "ask": False,
        "q": None,
        "mem": [],
        "reuse": [],
        "avoid": []
    }

    def _fail(requirement, context, used):
        raise RuntimeError(
            "no healthy Registry capability for task_class="
            + str(requirement.get("task_class") or "")
        )

    monkeypatch.setattr(
        "scripts.nvidia_semantic_planner_live_proof."
        "select_capability_for_requirement",
        _fail,
    )
    result = _validate_response(
        json.dumps(compact),
        {"resource_bounds": {"max_tasks_per_mission": 4}},
    )
    assert result["JSON_PARSE_VALID"] is True
    assert result["MISSION_PROPOSAL_SCHEMA_VALID"] is True
    assert result["HARNESS_VALIDATION_PASS"] is False
    assert result["FAILED_REQUIREMENT"]["task_class"] == "DEVELOPMENT"
    assert result["REQUIREMENT_SUMMARIES"][0]["action"] == "DEVELOPMENT"
