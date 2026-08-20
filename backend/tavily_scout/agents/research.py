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

from tavily_scout.agents.prompts import research_system_prompt
from tavily_scout.config import get_settings
from tavily_scout.models import DEFAULT_MODEL, resolve_model


@dataclass
class ResearchContext:
    """Per-run model id used for thread-level swapping."""

    model: str = DEFAULT_MODEL


def _provider_and_name(model_id: str) -> tuple[str, str]:
    provider, _, name = model_id.partition("/")
    if not name:
        return "openai", provider
    return provider, name


def _chat_model(requested_model: str):
    model_id = resolve_model(requested_model) or DEFAULT_MODEL
    provider, name = _provider_and_name(model_id)
    _ensure_harness(provider)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for ChatOpenAI")
        return ChatOpenAI(model=name, use_responses_api=True)
    if provider == "nebius":
        from langchain_nebius import ChatNebius

        if not os.environ.get("NEBIUS_API_KEY"):
            raise RuntimeError("NEBIUS_API_KEY is required for ChatNebius")
        return ChatNebius(model=name)
    raise RuntimeError(f"Unsupported model provider: {provider}")


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
        request.override(model=_chat_model(_requested_model_from_request(request)))
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


def _ensure_harness(provider: str) -> None:
    """Disable Deep Agent extras so this agent exposes only Tavily tools."""
    global _harness_profile
    if provider in _harness_ids:
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
    # ChatNebius subclasses the OpenAI chat client, so Deep Agents may resolve
    # it as either ``nebius`` or ``openai``. Register both.
    for profile_id in {provider, "openai", "nebius"}:
        if profile_id in _harness_ids:
            continue
        register_harness_profile(profile_id, _harness_profile)
        _harness_ids.add(profile_id)


def build_research_agent():
    """Build the in-process graph used by the Slack turn runner."""
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("deepagents is not installed; run `uv sync`") from exc

    settings = get_settings()
    return create_deep_agent(
        model=_chat_model(DEFAULT_MODEL),
        tools=_tavily_tools(),
        system_prompt=research_system_prompt(),
        middleware=[
            _swap_selected_model,
            ModelCallLimitMiddleware(run_limit=settings.max_model_calls),
            ToolCallLimitMiddleware(run_limit=settings.max_tool_calls),
        ],
        context_schema=ResearchContext,
        checkpointer=InMemorySaver(),
        name="tavily-scout-slack-agent",
    )
