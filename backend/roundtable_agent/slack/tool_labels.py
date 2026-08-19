"""Turn tool calls into compact Slack arguments, result summaries, and links.

In-process LangGraph callbacks return ``ToolMessage`` objects, while remote
streams return dictionaries. Normalize both so Slack shows useful result
counts and sources instead of the message object's serialized character size.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from roundtable_agent.slack.progress import format_params, format_result_shape

_DETAILS_MAX = 120
_OUTPUT_MAX = 400
_SOURCE_TEXT_MAX = 75
_MAX_SOURCES = 3
_EXC_INNER = re.compile(r"Exception\((['\"])(.+?)\1\)")
_HTTP_ERROR = re.compile(r"Error \d{3}:\s*.+")

TOOL_TITLES: dict[str, str] = {
    "tavily_search": "Searching the web",
    "tavily_extract": "Reading sources",
}


@dataclass(frozen=True, slots=True)
class ToolSummary:
    title: str
    details: str
    output: str
    sources: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


def summarize_tool(name: str, params: Any, output: Any) -> ToolSummary:
    """One pass: unwrap LangGraph envelopes, then error or shape + URLs."""
    payload = _unwrap(output)
    err = _error_message(payload)
    details = _plain(format_params(params).replace("`", ""), _DETAILS_MAX)
    if err:
        return ToolSummary(
            title=tool_title(name),
            details=details,
            output=_plain(err, _OUTPUT_MAX),
            error=err,
        )
    return ToolSummary(
        title=tool_title(name),
        details=details,
        output=_plain(_shape(payload), _OUTPUT_MAX),
        sources=_source_urls(payload),
    )


def tool_title(name: str) -> str:
    if name in TOOL_TITLES:
        return TOOL_TITLES[name]
    return (name or "tool").replace("_", " ")


def tool_details(name: str, params: Any) -> str:
    return summarize_tool(name, params, None).details


def tool_output(name: str, output: Any) -> str:
    return summarize_tool(name, None, output).output


def tool_sources(name: str, output: Any) -> list[dict[str, str]]:
    return summarize_tool(name, None, output).sources


def tool_error(output: Any) -> str | None:
    return _error_message(_unwrap(output))


def _unwrap(output: Any) -> Any:
    current = output
    for _ in range(6):
        if current is None:
            return None
        message_content = _message_content(current)
        if message_content is not _NOT_A_MESSAGE:
            current = message_content
            continue
        if isinstance(current, str):
            text = current.strip()
            if text.startswith(("{", "[")):
                try:
                    current = json.loads(text)
                    continue
                except json.JSONDecodeError:
                    return current
            return current
        if not isinstance(current, dict):
            return current
        if isinstance(current.get("results"), list) or current.get("ok") is False:
            return current
        if current.get("error") is not None and "content" not in current:
            return current
        typ = str(current.get("type") or current.get("role") or "")
        if typ in {"tool", "ToolMessage"} and "content" in current:
            current = current.get("content")
            continue
        if current.get("tool_call_id") and "content" in current:
            current = current.get("content")
            continue
        nested = current.get("output")
        if nested is None:
            nested = current.get("result")
        if nested is not None and nested is not current:
            current = nested
            continue
        return current
    return current


_NOT_A_MESSAGE = object()


def _message_content(value: Any) -> Any:
    """Unwrap a LangChain message object without importing message classes."""
    if isinstance(value, (str, bytes, bytearray, dict, list, BaseException)):
        return _NOT_A_MESSAGE
    if not hasattr(value, "content"):
        return _NOT_A_MESSAGE

    content = getattr(value, "content", None)
    if getattr(value, "status", None) == "error":
        return {"error": content or "Tool call failed"}

    # Some tools keep the structured response in ``artifact`` and put a
    # model-facing rendering in ``content``. Prefer the structured form.
    artifact = getattr(value, "artifact", None)
    return artifact if artifact is not None else content


def _error_message(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, BaseException):
        return _clean_error(payload)
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            return _clean_error(
                payload.get("error") or payload.get("message") or "error"
            )
        if payload.get("error") is not None:
            return _clean_error(payload["error"])
        return None
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        lowered = text.lower()
        looks_like_error = (
            text.startswith(("{'error':", '{"error":'))
            or "exception(" in lowered
            or bool(_HTTP_ERROR.search(text))
        )
        if not looks_like_error:
            return None
        inner = _EXC_INNER.search(text)
        if inner:
            return inner.group(2)
        http = _HTTP_ERROR.search(text)
        if http:
            return http.group(0)
        return _plain(text, 200)
    return None


def _clean_error(value: Any) -> str:
    text = str(value).strip()
    inner = _EXC_INNER.search(text)
    if inner:
        return inner.group(2)
    http = _HTTP_ERROR.search(text)
    if http:
        return http.group(0)
    return _plain(text, _OUTPUT_MAX)


def _shape(payload: Any) -> str:
    n = _result_count(payload)
    if n is not None:
        return "1 result" if n == 1 else f"{n} results"
    if isinstance(payload, dict):
        title = _str(payload.get("title"))
        if _str(payload.get("url")):
            return title or "loaded"
    if (
        isinstance(payload, str)
        and len(payload) < 80
        and "error" not in payload.lower()
    ):
        return payload.strip() or "done"
    return format_result_shape(payload)


def _source_urls(payload: Any) -> list[dict[str, str]]:
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            items = results
        elif _str(payload.get("url")):
            items = [payload]
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = _str(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(_source(url, _str(item.get("title"))))
        if len(sources) >= _MAX_SOURCES:
            break
    return sources


def _result_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        total = payload.get("total")
        if isinstance(total, int):
            return total
        size = payload.get("size")
        if isinstance(size, int):
            return size
        results = payload.get("results")
        if isinstance(results, list):
            return len(results)
    if isinstance(payload, list):
        return len(payload)
    return None


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _plain(value: str, max_len: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def _source(url: str, title: str) -> dict[str, str]:
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    text = _plain(title, _SOURCE_TEXT_MAX) if title else _host(url)
    return {"type": "url", "url": url, "text": text or url}


def _host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc or url
