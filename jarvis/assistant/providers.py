"""LocalLLMProvider abstraction: today only OllamaProvider exists, but
callers (llm_client.py, scripts/import_resume.py, jarvis/indexing/proposer.py)
depend on this Protocol, not on `ollama` directly -- so a future MLXProvider
can be dropped in via get_provider() without touching any caller."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ollama import Client

from jarvis.assistant.tool_schema import ToolSpec, tool_spec_to_openai_dict


@dataclass
class ToolCallRequest:
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    content: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


class LocalLLMProvider(Protocol):
    def chat(self, messages: list[dict], tool_specs: list[ToolSpec]) -> ProviderResponse: ...

    def structured_chat(self, messages: list[dict], json_schema: dict) -> dict: ...


class OllamaProvider:
    def __init__(self, model: str, host: str, client: Client | None = None) -> None:
        self._model = model
        self._client = client or Client(host=host)

    def chat(self, messages: list[dict], tool_specs: list[ToolSpec]) -> ProviderResponse:
        tools = [tool_spec_to_openai_dict(spec) for spec in tool_specs]
        response = self._client.chat(model=self._model, messages=messages, tools=tools)
        message = response.message
        calls = [
            ToolCallRequest(name=call.function.name, arguments=dict(call.function.arguments))
            for call in (message.tool_calls or [])
        ]
        return ProviderResponse(content=message.content or "", tool_calls=calls)

    def structured_chat(self, messages: list[dict], json_schema: dict) -> dict:
        response = self._client.chat(
            model=self._model,
            messages=messages,
            format=json_schema,
            options={"temperature": 0},
        )
        return json.loads(response.message.content)


def get_provider(model: str | None = None, host: str | None = None) -> LocalLLMProvider:
    from jarvis.config import LLM_PROVIDER, LOCAL_MODEL, OLLAMA_HOST

    if LLM_PROVIDER == "ollama":
        return OllamaProvider(model=model or LOCAL_MODEL, host=host or OLLAMA_HOST)
    raise ValueError(f"Provedor de LLM desconhecido: {LLM_PROVIDER!r}")
