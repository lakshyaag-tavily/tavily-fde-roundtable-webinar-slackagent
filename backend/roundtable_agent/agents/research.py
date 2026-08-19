"""A small LangChain Deep Agent with Tavily search and extract tools."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
    wrap_model_call,
)
from langchain_tavily import TavilyExtract, TavilySearch
from langgraph.checkpoint.memory import InMemorySaver

from roundtable_agent.agents.prompts import research_system_prompt
from roundtable_agent.config import get_settings
from roundtable_agent.models import DEFAULT_MODEL, resolve_model

_GATEWAY_BASE_URL = "https://gateway.smith.langchain.com/v1"


@dataclass
class ResearchContext:
    """Per-run LangSmith LLM Gateway model id."""

    model: str = DEFAULT_MODEL


def _gateway_chat_model(requested_model: str):
    from langchain_openai import ChatOpenAI

    model_id = resolve_model(requested_model) or DEFAULT_MODEL
    _ensure_harness(model_id)
    key = os.environ.get("LANGSMITH_API_KEY")
    if not key:
        raise RuntimeError(
            "LANGSMITH_API_KEY is required for the LangSmith LLM Gateway"
        )
    base_url = (
        os.environ.get("LANGSMITH_GATEWAY_BASE_URL") or _GATEWAY_BASE_URL
    ).rstrip("/")
    return ChatOpenAI(model=model_id, api_key=key, base_url=base_url)


def _requested_model_from_request(request: ModelRequest) -> str:
    raw = None
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None) if runtime is not None else None
    if context is not None:
        raw = getattr(context, "model", None)
        if raw is None and isinstance(context, dict):
            raw = context.get("model")
    if not raw and runtime is not None:
        config = getattr(runtime, "config", None) or {}
        if isinstance(config, dict):
            raw = (config.get("configurable") or {}).get("model")
    return resolve_model(str(raw) if raw else None) or DEFAULT_MODEL


@wrap_model_call
async def _swap_selected_model(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    return await handler(
        request.override(
            model=_gateway_chat_model(_requested_model_from_request(request))
        )
    )


def _tavily_tools() -> list:
    settings = get_settings()
    key = os.environ.get("TAVILY_API_KEY") or settings.tavily_api_key
    if key and not os.environ.get("TAVILY_API_KEY"):
        os.environ["TAVILY_API_KEY"] = key
    return [
        TavilySearch(max_results=10, search_depth="advanced"),
        TavilyExtract(extract_depth="advanced"),
    ]


_harness_ids: set[str] = set()
_harness_profile: object | None = None


def _ensure_harness(requested_model: str) -> None:
    """Disable Deep Agent extras so this agent exposes only Tavily tools."""
    global _harness_profile
    if requested_model in _harness_ids:
        return

    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        register_harness_profile,
    )

    if _harness_profile is None:
        _harness_profile = HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            excluded_tools=frozenset(
                {
                    "task",
                    "write_todos",
                    "read_file",
                    "write_file",
                    "edit_file",
                    "delete",
                    "ls",
                    "glob",
                    "grep",
                    "execute",
                }
            ),
        )
    # All gateway models use ChatOpenAI's OpenAI-compatible client, so the
    # resolved provider is ``openai`` even for an anthropic/... gateway id.
    register_harness_profile("openai", _harness_profile)
    _harness_ids.add(requested_model)


def build_research_agent():
    """Build the in-process graph used by the Slack turn runner."""
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("deepagents is not installed; run `uv sync`") from exc

    settings = get_settings()
    _ensure_harness(DEFAULT_MODEL)
    return create_deep_agent(
        model=_gateway_chat_model(DEFAULT_MODEL),
        tools=_tavily_tools(),
        system_prompt=research_system_prompt(),
        middleware=[
            _swap_selected_model,
            ModelCallLimitMiddleware(run_limit=settings.max_model_calls),
            ToolCallLimitMiddleware(run_limit=settings.max_tool_calls),
        ],
        context_schema=ResearchContext,
        checkpointer=InMemorySaver(),
        name="roundtable-slack-research-agent",
    )
