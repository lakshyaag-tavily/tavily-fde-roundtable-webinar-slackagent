"""Run Slack turns directly against the in-process Deep Agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tavily_scout.agents.research import ResearchContext, build_research_agent
from tavily_scout.config import Settings, get_settings
from tavily_scout.model_selection import model_for_thread
from tavily_scout.services.slack import SlackService
from tavily_scout.slack.tool_plan import ToolCallTracker

logger = logging.getLogger(__name__)

_AGENT_LOADING_MESSAGES = [
    "Understanding the question…",
    "Searching the web…",
    "Taking a closer look…",
    "Preparing a concise answer…",
]
_seen_events: set[str] = set()
_thread_locks: dict[str, asyncio.Lock] = {}
_research_graph: Any | None = None


def _graph() -> Any:
    global _research_graph
    if _research_graph is None:
        _research_graph = build_research_agent()
    return _research_graph


def _last_ai_text(values: dict[str, Any] | None) -> str | None:
    messages = (values or {}).get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        role = (
            getattr(message, "type", None)
            or getattr(message, "role", None)
            or (
                message.get("type") or message.get("role")
                if isinstance(message, dict)
                else None
            )
        )
        content = (
            getattr(message, "content", None)
            if not isinstance(message, dict)
            else message.get("content")
        )
        if role not in {"ai", "assistant"}:
            continue
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
            if text:
                return text
    return None


async def _set_agent_status(
    slack: SlackService,
    *,
    channel: str,
    thread_ts: str,
    active: bool,
) -> None:
    await asyncio.to_thread(
        slack.set_agent_status,
        channel=channel,
        thread_ts=thread_ts,
        status="is working on your request..." if active else "",
        loading_messages=_AGENT_LOADING_MESSAGES if active else None,
    )


async def _run_agent(
    *,
    slack: SlackService,
    channel: str,
    thread_ts: str,
    user_id: str,
    text: str,
    settings: Settings,
) -> str:
    graph = _graph()
    thread_key = f"slack:{channel}:{thread_ts}"
    model_id = model_for_thread(user_id=user_id, thread_key=thread_key)
    config = {
        "configurable": {"thread_id": thread_key},
        "recursion_limit": settings.recursion_limit,
    }
    tracker = ToolCallTracker()
    plan_ts: str | None = None
    use_plan_blocks = True

    async def refresh_tool_plan(*, done: bool = False) -> None:
        nonlocal plan_ts, use_plan_blocks
        if not settings.slack_stream_tools or not tracker.has_calls():
            return
        plan_ts, use_plan_blocks = await asyncio.to_thread(
            slack.post_or_update_tool_plan,
            channel=channel,
            thread_ts=thread_ts,
            calls=tracker.get_calls(),
            title="Web research (done)" if done else "Web research",
            message_ts=plan_ts,
            use_plan_blocks=use_plan_blocks,
        )

    async with asyncio.timeout(settings.run_timeout_seconds):
        async for event in graph.astream_events(
            {"messages": [{"role": "user", "content": text}]},
            config=config,
            context=ResearchContext(model=model_id),
            version="v2",
        ):
            if tracker.apply_sse("events", event):
                await refresh_tool_plan()

    if tracker.has_calls():
        await refresh_tool_plan(done=True)

    state = await graph.aget_state(config)
    reply = _last_ai_text(dict(state.values))
    if not reply:
        raise RuntimeError("The agent completed without a text response")
    return reply


async def handle_slack_message(
    *,
    event_id: str,
    channel: str,
    user_id: str,
    text: str,
    thread_ts: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Deduplicate, serialize a Slack thread, stream tools, and post the answer."""
    if event_id in _seen_events:
        return {"event_id": event_id, "status": "duplicate"}
    _seen_events.add(event_id)

    settings = settings or get_settings()
    slack = SlackService(settings)
    thread_key = f"{channel}:{thread_ts}"
    lock = _thread_locks.setdefault(thread_key, asyncio.Lock())

    async with lock:
        await _set_agent_status(
            slack, channel=channel, thread_ts=thread_ts, active=True
        )
        try:
            reply = await _run_agent(
                slack=slack,
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                text=text,
                settings=settings,
            )
            await asyncio.to_thread(
                slack.post_agent_reply,
                channel=channel,
                text=reply,
                thread_ts=thread_ts,
            )
            return {"event_id": event_id, "status": "completed"}
        except Exception as exc:
            logger.exception("Agent turn failed event_id=%s", event_id)
            await asyncio.to_thread(
                slack.post_message,
                channel=channel,
                text="Sorry — that request failed. Please try again.",
                thread_ts=thread_ts,
            )
            return {
                "event_id": event_id,
                "status": "failed",
                "error": type(exc).__name__,
            }
        finally:
            await _set_agent_status(
                slack, channel=channel, thread_ts=thread_ts, active=False
            )
