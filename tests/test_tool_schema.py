from jarvis.assistant.tool_schema import (
    function_to_tool_spec,
    functions_to_tool_specs,
    tool_spec_to_openai_dict,
)
from jarvis.assistant.tools import TOOLS, read_resume, update_resume_field


def test_function_to_tool_spec_no_args():
    spec = function_to_tool_spec(read_resume)
    assert spec.name == "read_resume"
    assert spec.description
    assert spec.parameters == {"type": "object", "properties": {}, "required": []}


def test_function_to_tool_spec_with_args():
    spec = function_to_tool_spec(update_resume_field)
    assert spec.name == "update_resume_field"
    assert set(spec.parameters["properties"]) == {"path", "value"}
    assert spec.parameters["required"] == ["path", "value"]
    assert spec.parameters["properties"]["path"]["type"] == "string"
    assert spec.parameters["properties"]["path"]["description"]


def test_functions_to_tool_specs_covers_all_tools():
    specs = functions_to_tool_specs(TOOLS)
    assert {s.name for s in specs} == {f.__name__ for f in TOOLS}


def test_tool_spec_to_openai_dict_shape():
    spec = function_to_tool_spec(read_resume)
    d = tool_spec_to_openai_dict(spec)
    assert d["type"] == "function"
    assert d["function"]["name"] == "read_resume"
    assert "parameters" in d["function"]
