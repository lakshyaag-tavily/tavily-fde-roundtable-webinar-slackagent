"""Slack Thinking Steps plan/task_card blocks for tool-call debug.

Fed from LangGraph ``events`` SSE (``on_tool_start`` / ``on_tool_end`` /
``on_tool_error``). Labels come from ``tool_labels`` (human titles, compact
details, result counts, URL chips) — never full tool bodies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from tavily_scout.slack.progress import format_params
from tavily_scout.slack.tool_labels import (
    tool_details,
    tool_error,
    tool_output,
    tool_sources,
    tool_title,
)

_OUTPUT_MAX = 400
_MAX_TASKS = 25


@dataclass
class ActiveToolCall:
    """One tool invocation shown as a Slack task_card."""

    call_id: str
    name: str
    status: str = "in_progress"  # pending | in_progress | complete | error
    params: Any = None
    output: Any = None
    result_preview: str | None = None
    error: str | None = None

    def display_title(self) -> str:
        return tool_title(self.name)

    def details_text(self) -> str:
        """Human-readable input summary for the task card details field."""
        return tool_details(self.name, self.params)

    def output_text(self) -> str:
        if self.error:
            return _truncate_plain(self.error, _OUTPUT_MAX)
        if self.status in {"pending", "in_progress"} and self.output is None:
            return ""
        if self.result_preview:
            return self.result_preview
        return tool_output(self.name, self.output)

    def source_elements(self) -> list[dict[str, str]]:
        if self.status == "error":
            return []
        return tool_sources(self.name, self.output)


@dataclass
class ToolCallTracker:
    """Accumulate tool lifecycle events into ordered ActiveToolCall rows."""

    calls: dict[str, ActiveToolCall] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)

    def get_calls(self) -> list[ActiveToolCall]:
        return [self.calls[cid] for cid in self._order if cid in self.calls]

    def has_calls(self) -> bool:
        return bool(self._order)

    def apply_sse(self, event_type: str | None, data: Any) -> bool:
        """Apply one SSE frame. Returns True when plan UI should refresh."""
        payload = _unwrap(event_type, data)
        if not isinstance(payload, dict):
            return False

        if isinstance(payload.get("event"), str):
            return self._from_callback(payload)

        # ToolMessage fallback (messages-tuple).
        if (
            payload.get("type") in {"tool", "ToolMessage"}
            or payload.get("role") == "tool"
        ):
            return self._from_tool_message(payload)
        return False

    def _from_callback(self, event: dict[str, Any]) -> bool:
        etype = str(event.get("event") or "")
        name = str(event.get("name") or "tool")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        call_id = _tool_run_id(event, fallback=f"{etype}:{name}")

        if etype in {"on_tool_start", "on_tool_start_run"}:
            params = data.get("input", data)
            return self._upsert_start(call_id, name, params)

        if etype in {"on_tool_end", "on_tool_end_run"}:
            params = data.get("input")
            output = data.get("output")
            if output is None:
                output = data.get("result")
            return self._upsert_done(call_id, name, params, output)

        if etype == "on_tool_error":
            err = data.get("error") or data.get("message") or "error"
            return self._upsert_error(call_id, name, str(err))

        return False

    def _from_tool_message(self, msg: dict[str, Any]) -> bool:
        name = str(msg.get("name") or "tool")
        call_id = str(msg.get("tool_call_id") or msg.get("id") or name)
        return self._upsert_done(call_id, name, None, msg.get("content"))

    def _upsert_start(self, call_id: str, name: str, params: Any) -> bool:
        existing = self.calls.get(call_id)
        if existing is None:
            self.calls[call_id] = ActiveToolCall(
                call_id=call_id,
                name=name,
                status="in_progress",
                params=params,
            )
            self._order.append(call_id)
            self._trim()
            return True
        changed = False
        if name and existing.name in {"tool", "..."}:
            existing.name = name
            changed = True
        if params is not None and (
            existing.params is None or _params_richer(params, existing.params)
        ):
            existing.params = params
            changed = True
        if existing.status == "pending":
            existing.status = "in_progress"
            changed = True
        return changed

    def _upsert_done(self, call_id: str, name: str, params: Any, output: Any) -> bool:
        err = tool_error(output)
        if err:
            if params is not None:
                existing = self.calls.get(call_id)
                if existing is not None and (
                    existing.params is None or _params_richer(params, existing.params)
                ):
                    existing.params = params
            return self._upsert_error(call_id, name, err)
        existing = self.calls.get(call_id)
        preview = tool_output(name, output)
        if existing is None:
            self.calls[call_id] = ActiveToolCall(
                call_id=call_id,
                name=name,
                status="complete",
                params=params,
                output=output,
                result_preview=preview,
            )
            self._order.append(call_id)
            self._trim()
            return True
        existing.status = "complete"
        if name and existing.name in {"tool", "..."}:
            existing.name = name
        if params is not None and (
            existing.params is None or _params_richer(params, existing.params)
        ):
            existing.params = params
        existing.output = output
        existing.result_preview = preview
        existing.error = None
        return True

    def _upsert_error(self, call_id: str, name: str, error: str) -> bool:
        existing = self.calls.get(call_id)
        if existing is None:
            self.calls[call_id] = ActiveToolCall(
                call_id=call_id,
                name=name,
                status="error",
                error=error,
            )
            self._order.append(call_id)
            self._trim()
            return True
        existing.status = "error"
        existing.error = error
        if name and existing.name in {"tool", "..."}:
            existing.name = name
        return True

    def _trim(self) -> None:
        while len(self._order) > _MAX_TASKS:
            old = self._order.pop(0)
            self.calls.pop(old, None)

    def fallback_lines(self) -> list[str]:
        """Plain mrkdwn lines when plan/task_card blocks are rejected."""
        lines: list[str] = []
        for call in self.get_calls():
            title = call.display_title()
            details = call.details_text()
            if call.status == "in_progress":
                text = f"→ *{title}*"
                if details:
                    text += f" · {details}"
            elif call.status == "error":
                text = f"✗ *{title}* · `{call.output_text() or 'error'}`"
            else:
                text = f"✓ *{title}*"
                if details:
                    text += f" · {details}"
                out = call.output_text()
                if out:
                    text += f" → {out}"
            lines.append(text)
        return lines


def tool_plan_blocks(
    calls: list[ActiveToolCall],
    *,
    title: str = "Tool activity",
    show_details: bool = True,
) -> list[dict[str, Any]]:
    """Slack Thinking Steps plan block wrapping one task_card per tool call."""
    tasks = [_task_card(call, show_details=show_details) for call in calls]
    if not tasks:
        return [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": ":wrench: *Tool activity* (debug)"}
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_Waiting for tools…_"},
            },
        ]
    return [
        {
            "type": "plan",
            "title": title,
            "tasks": tasks,
        }
    ]


def _task_card(call: ActiveToolCall, *, show_details: bool) -> dict[str, Any]:
    task: dict[str, Any] = {
        "type": "task_card",
        "task_id": call.call_id[:255],
        "title": (call.display_title() or "tool")[:150],
        "status": call.status
        if call.status in {"pending", "in_progress", "complete", "error"}
        else "in_progress",
    }
    if show_details:
        details = call.details_text()
        if details:
            task["details"] = _rich_text(details)
        output = _output_rich_text(call)
        if output:
            task["output"] = output
    return task


def _output_rich_text(call: ActiveToolCall) -> dict[str, Any] | None:
    """One line: shape + up to 3 hostname links (no stacked source chips)."""
    elements: list[dict[str, Any]] = []
    text = call.output_text()
    if text:
        elements.append({"type": "text", "text": text})
    if call.status != "error":
        for src in call.source_elements():
            url = src.get("url") or ""
            if not url:
                continue
            label = _hostname(url) or src.get("text") or url
            if elements:
                elements.append({"type": "text", "text": " · "})
            elements.append({"type": "link", "url": url, "text": label[:40]})
    if not elements:
        return None
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": elements}],
    }


def _hostname(url: str) -> str:
    host = urlparse(url).netloc
    host = host.removeprefix("www.")
    return host


def _rich_text(text: str) -> dict[str, Any]:
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [{"type": "text", "text": text}],
            }
        ],
    }


def _unwrap(event_type: str | None, data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, list) and len(data) == 2 and isinstance(data[0], str):
        mode, payload = data
        if mode in {"events", "messages", "messages-tuple", "custom"} or event_type in {
            "events",
            "messages",
            "messages-tuple",
            "custom",
        }:
            data = payload
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and (
            "type" in first
            or "tool_calls" in first
            or "role" in first
            or "event" in first
        ):
            return first
    return data


def _tool_run_id(data: dict[str, Any], *, fallback: str) -> str:
    for key in ("run_id", "tool_call_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("tool_call_id", "id", "run_id"):
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


def _params_richer(new: Any, old: Any) -> bool:
    new_text = format_params(new)
    old_text = format_params(old)
    if new_text and not old_text:
        return True
    if isinstance(new, dict) and isinstance(old, dict) and len(new) > len(old):
        return True
    return len(str(new)) > len(str(old))


def _truncate_plain(value: str, max_len: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"
