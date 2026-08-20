"""Parse LangGraph SSE tool events into short Slack progress lines.

Shows tool name + interesting params and result *shape* only — never bodies.
Prefer ``stream_mode=events`` (on_tool_start/end); ignore partial message chunks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_PARAM_VALUE_MAX = 100
_LINE_MAX = 300

# Never echo these values into Slack.
_BODY_KEYS = frozenset(
    {
        "content",
        "output",
        "result",
        "results",
        "messages",
        "text",
        "answer",
        "raw_content",
        "documents",
        "follow_up_questions",
        "images",
    }
)

# Drop noise / defaults from Tavily and similar tools.
_SKIP_PARAM_KEYS = frozenset(
    {
        "include_images",
        "include_image_descriptions",
        "include_raw_content",
        "include_favicon",
        "include_answer",
        "time_range",
        "start_date",
        "end_date",
        "topic",
        "country",
        "exact_match",
        "max_results",
        "search_depth",
        "extract_depth",
        "include_domains",
        "exclude_domains",
        "chunks_per_source",
    }
)

# Prefer these keys first in the summary.
_PREFERRED_KEYS = ("query", "queries", "urls", "url", "file_path", "path", "command")


@dataclass(frozen=True, slots=True)
class ProgressLine:
    """One append-only Slack progress message."""

    key: str
    text: str


def _truncate(value: str, max_len: int = _PARAM_VALUE_MAX) -> str:
    value = " ".join(value.split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def _is_empty_param(value: Any) -> bool:
    if value is None:
        return True
    if value is False:
        return True
    if value == "":
        return True
    return value == [] or value == {}


def format_params(params: Any) -> str:
    """Compact, human-friendly param summary (query-first, no defaults noise)."""
    if params is None:
        return ""
    if isinstance(params, str):
        return f"`{_truncate(params)}`"
    if isinstance(params, (int, float, bool)):
        return f"`{params}`"
    if isinstance(params, list):
        if not params:
            return ""
        if all(isinstance(x, str) for x in params):
            joined = ", ".join(_truncate(x, 40) for x in params[:3])
            extra = f" +{len(params) - 3}" if len(params) > 3 else ""
            return f"`{joined}{extra}`"
        return f"{len(params)} items"
    if not isinstance(params, dict):
        return f"`{_truncate(str(params))}`"

    # Prefer concrete targets (URLs/paths) over a filter query.
    urls = params.get("urls") or params.get("url")
    if isinstance(urls, str) and urls.strip():
        return f"`{_truncate(urls.strip())}`"
    if isinstance(urls, list) and urls:
        shown = ", ".join(_truncate(str(u), 50) for u in urls[:2])
        extra = f" +{len(urls) - 2}" if len(urls) > 2 else ""
        return f"`{shown}{extra}`"

    query = params.get("query")
    if isinstance(query, str) and query.strip():
        return f"`{_truncate(query.strip())}`"

    parts: list[str] = []
    seen: set[str] = set()
    for key in _PREFERRED_KEYS:
        if key not in params or key in seen:
            continue
        seen.add(key)
        value = params[key]
        if key in _SKIP_PARAM_KEYS or _is_empty_param(value):
            continue
        if key in _BODY_KEYS or isinstance(value, (dict, list)):
            parts.append(f"{key}={_shape_short(value)}")
        else:
            parts.append(f"{key}=`{_truncate(str(value))}`")

    for key, value in params.items():
        if key in seen or key in _SKIP_PARAM_KEYS:
            continue
        if _is_empty_param(value):
            continue
        if key in _BODY_KEYS or isinstance(value, (dict, list)):
            parts.append(f"{key}={_shape_short(value)}")
        else:
            parts.append(f"{key}=`{_truncate(str(value))}`")
        if len(parts) >= 4:
            break

    return " · ".join(parts)


def _shape_short(value: Any) -> str:
    if value is None:
        return "empty"
    if isinstance(value, str):
        return f"{len(value)}chars"
    if isinstance(value, list):
        return f"{len(value)} items"
    if isinstance(value, dict):
        return f"{len(value)} keys"
    if isinstance(value, (bytes, bytearray)):
        return f"{len(value)}bytes"
    return type(value).__name__


def _chars_label(n: int) -> str:
    if n >= 1000:
        return f"~{n / 1000:.0f}k chars"
    return f"{n} chars"


def format_result_shape(output: Any) -> str:
    """Human-readable shape/length of a tool result (no content)."""
    if output is None:
        return "empty"
    if isinstance(output, str):
        text = output.strip()
        if text.startswith(("{", "[")):
            try:
                return format_result_shape(json.loads(text))
            except json.JSONDecodeError:
                pass
        return _chars_label(len(output))
    if isinstance(output, list):
        return f"{len(output)} items"
    if isinstance(output, dict):
        results = output.get("results")
        if isinstance(results, list):
            n = len(results)
            return "1 result" if n == 1 else f"{n} results"
        total = output.get("total")
        if isinstance(total, int):
            return "1 result" if total == 1 else f"{total} results"
        try:
            return _chars_label(len(json.dumps(output, default=str)))
        except TypeError:
            return _chars_label(len(str(output)))
    if isinstance(output, (bytes, bytearray)):
        return f"{len(output)} bytes"
    return f"{type(output).__name__} · {_chars_label(len(str(output)))}"


def _has_useful_params(params: Any) -> bool:
    """True when we have something worth showing (avoid bare → tool lines)."""
    text = format_params(params)
    return bool(text.strip())


def _tool_run_id(data: dict[str, Any], fallback: str) -> str:
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


def _display_name(name: str) -> str:
    # Default langchain-tavily tool name is often "tavily_search".
    return name or "tool"


def _start_line(name: str, params: Any) -> str:
    param_text = format_params(params)
    label = _display_name(name)
    if param_text:
        return _truncate(f"→ *{label}* · {param_text}", _LINE_MAX)
    return _truncate(f"→ *{label}*", _LINE_MAX)


def _done_line(name: str, params: Any, output: Any) -> str:
    label = _display_name(name)
    param_text = format_params(params) if params is not None else ""
    shape = format_result_shape(output)
    if param_text:
        return _truncate(f"✓ *{label}* · {param_text} → {shape}", _LINE_MAX)
    return _truncate(f"✓ *{label}* → {shape}", _LINE_MAX)


def progress_lines_from_sse(event_type: str | None, data: Any) -> list[ProgressLine]:
    """Map one LangGraph SSE frame into zero or more Slack progress lines."""
    payload = _unwrap_payload(event_type, data)
    if payload is None:
        return []

    # Prefer LangChain callback events — full args, no token-stream partials.
    if isinstance(payload, dict) and isinstance(payload.get("event"), str):
        return _from_callback_event(payload)

    # messages-tuple: only complete ToolMessage dones as a fallback.
    # Skip AIMessage tool_calls — those stream in incomplete chunks.
    if isinstance(payload, dict) and (
        payload.get("type") in {"tool", "ToolMessage"} or payload.get("role") == "tool"
    ):
        return _from_tool_message(payload)

    return []


def _unwrap_payload(event_type: str | None, data: Any) -> Any:
    """Normalize multi-mode SSE envelopes to the inner payload."""
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


def _from_callback_event(event: dict[str, Any]) -> list[ProgressLine]:
    name = str(event.get("name") or "tool")
    etype = str(event.get("event") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    run_id = _tool_run_id(event, fallback=f"{etype}:{name}")

    if etype in {"on_tool_start", "on_tool_start_run"}:
        params = data.get("input", data)
        # Skip empty starts — a later start or the done line will carry the query.
        if not _has_useful_params(params):
            return []
        return [
            ProgressLine(
                key=f"start:{run_id}:{name}",
                text=_start_line(name, params),
            )
        ]

    if etype in {"on_tool_end", "on_tool_end_run"}:
        params = data.get("input")
        output = data.get("output")
        if output is None:
            output = data.get("result")
        return [
            ProgressLine(
                key=f"done:{run_id}:{name}",
                text=_done_line(name, params, output),
            )
        ]

    if etype in {"on_tool_error"}:
        err = data.get("error") or data.get("message") or "error"
        text = f"✗ *{_display_name(name)}* · `{_truncate(str(err), 120)}`"
        return [
            ProgressLine(key=f"err:{run_id}:{name}", text=_truncate(text, _LINE_MAX))
        ]

    return []


def _from_tool_message(msg: dict[str, Any]) -> list[ProgressLine]:
    name = str(msg.get("name") or "tool")
    call_id = str(msg.get("tool_call_id") or msg.get("id") or name)
    content = msg.get("content")
    return [
        ProgressLine(
            key=f"done:{call_id}:{name}",
            text=_done_line(name, None, content),
        )
    ]
