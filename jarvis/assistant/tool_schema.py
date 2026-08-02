"""Turns the plain Python functions in tools.py into provider-neutral tool
schemas ({"type": "function", "function": {...}} — the OpenAI-style shape
that Ollama, llama.cpp-server, and LM Studio's compatible endpoints all
accept). Deliberately independent of `ollama`'s own (private) introspection
so a future MLXProvider can reuse the exact same schemas."""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Any, Callable, get_args, get_origin

import docstring_parser


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


def _python_type_to_json_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)

    if origin is typing.Union:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])
        return {"type": "string"}

    if origin in (list, tuple):
        args = get_args(annotation)
        item_schema = _python_type_to_json_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_schema}

    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    return {"type": "string"}


def function_to_tool_spec(func: Callable[..., Any]) -> ToolSpec:
    doc = docstring_parser.parse(func.__doc__ or "")
    param_docs = {p.arg_name: (p.description or "") for p in doc.params}
    hints = typing.get_type_hints(func)
    signature = inspect.signature(func)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if name == "self":
            continue
        schema = _python_type_to_json_schema(hints.get(name, str))
        schema["description"] = param_docs.get(name, "")
        properties[name] = schema
        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = doc.short_description or (func.__doc__ or func.__name__).strip().splitlines()[0]

    return ToolSpec(
        name=func.__name__,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required},
    )


def functions_to_tool_specs(functions: list[Callable[..., Any]]) -> list[ToolSpec]:
    return [function_to_tool_spec(f) for f in functions]


def tool_spec_to_openai_dict(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }
