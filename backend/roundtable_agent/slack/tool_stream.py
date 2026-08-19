"""Turn LangGraph tool events into one compact live Slack message."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class ToolCall:
    id: str
    name: str
    status: str = "running"
    arguments: Any = None
    output: Any = None
    error: str | None = None


class ToolStream:
    def __init__(self) -> None:
        self.calls: dict[str, ToolCall] = {}
        self.order: list[str] = []

    def apply(self, event: dict[str, Any]) -> bool:
        kind = str(event.get("event") or "")
        if kind not in {"on_tool_start", "on_tool_end", "on_tool_error"}:
            return False
        name = str(event.get("name") or "tool")
        call_id = str(event.get("run_id") or event.get("id") or f"{kind}:{name}")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        call = self.calls.get(call_id)
        if call is None:
            call = ToolCall(id=call_id, name=name)
            self.calls[call_id] = call
            self.order.append(call_id)
        if kind == "on_tool_start":
            call.arguments = data.get("input", data)
            call.status = "running"
        elif kind == "on_tool_error":
            call.status = "error"
            call.error = str(data.get("error") or data.get("message") or "error")
        else:
            call.status = "done"
            call.output = data.get("output", data.get("result"))
        return True

    def lines(self) -> list[str]:
        return [_line(self.calls[call_id]) for call_id in self.order]


def _line(call: ToolCall) -> str:
    title = {
        "tavily_search": "Searching the web",
        "tavily_extract": "Reading sources",
    }.get(call.name, call.name.replace("_", " "))
    prefix = "→" if call.status == "running" else "✗" if call.status == "error" else "✓"
    target = _target(call.arguments)
    detail = call.error if call.status == "error" else _result(call.output)
    parts = [f"{prefix} *{title}*"]
    if target:
        parts.append(target)
    if detail:
        parts.append(detail)
    return " · ".join(parts)[:2900]


def _target(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return ""
    query = arguments.get("query")
    if isinstance(query, str) and query.strip():
        return f"`{query.strip()[:120]}`"
    urls = arguments.get("urls") or arguments.get("url")
    if isinstance(urls, str):
        urls = [urls]
    if isinstance(urls, list):
        return ", ".join(_slack_link(str(url)) for url in urls[:2])
    return ""


def _result(output: Any) -> str:
    value = _unwrap(output)
    results = value.get("results") if isinstance(value, dict) else value
    if isinstance(results, list):
        count = f"{len(results)} result{'s' if len(results) != 1 else ''}"
        links = [
            _slack_link(str(item["url"]))
            for item in results
            if isinstance(item, dict) and item.get("url")
        ][:2]
        return " · ".join([count, *links])
    if isinstance(value, str):
        return f"{len(value):,} characters"
    return "done" if value is not None else ""


def _unwrap(value: Any) -> Any:
    for _ in range(3):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except json.JSONDecodeError:
                return value
        if not isinstance(value, dict):
            return value
        if "results" in value:
            return value
        nested = value.get("content", value.get("output", value.get("result")))
        if nested is None or nested is value:
            return value
        value = nested
    return value


def _slack_link(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.") or url[:40]
    return f"<{url}|{host}>"
