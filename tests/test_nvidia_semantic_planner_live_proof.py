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
