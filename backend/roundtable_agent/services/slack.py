"""Small deterministic wrapper around the Slack Web API."""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from roundtable_agent.config import Settings, get_settings
from roundtable_agent.slack.formatting import markdown_to_slack
from roundtable_agent.slack.tool_plan import ActiveToolCall, tool_plan_blocks

logger = logging.getLogger(__name__)


class SlackService:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        if not settings.slack_bot_token:
            raise RuntimeError("ROUNDTABLE_AGENT_SLACK_BOT_TOKEN is not configured")
        self.client = WebClient(token=settings.slack_bot_token)

    def post_message(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "thread_ts": thread_ts,
            "mrkdwn": True,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if blocks:
            kwargs["blocks"] = blocks
        try:
            return dict(self.client.chat_postMessage(**kwargs).data)
        except SlackApiError as exc:
            logger.exception("chat.postMessage failed: %s", exc.response.get("error"))
            raise

    def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return dict(
                self.client.chat_update(
                    channel=channel,
                    ts=ts,
                    text=text,
                    blocks=blocks,
                ).data
            )
        except SlackApiError as exc:
            logger.exception("chat.update failed: %s", exc.response.get("error"))
            raise

    def post_agent_reply(self, *, channel: str, text: str, thread_ts: str) -> None:
        self.post_message(
            channel=channel,
            text=markdown_to_slack(text) or "…",
            thread_ts=thread_ts,
        )

    def set_agent_status(
        self,
        *,
        channel: str,
        thread_ts: str,
        status: str,
        loading_messages: list[str] | None = None,
    ) -> None:
        try:
            self.client.assistant_threads_setStatus(
                channel_id=channel,
                thread_ts=thread_ts,
                status=status,
                loading_messages=loading_messages,
            )
        except SlackApiError as exc:
            logger.warning(
                "assistant status unavailable: %s", exc.response.get("error")
            )

    def post_or_update_tool_plan(
        self,
        *,
        channel: str,
        thread_ts: str,
        calls: list[ActiveToolCall],
        title: str = "Web research",
        message_ts: str | None = None,
        use_plan_blocks: bool = True,
    ) -> tuple[str | None, bool]:
        """Render Slack plan/task cards, falling back to ordinary blocks."""
        fallback_lines = self._fallback_tool_lines(calls)
        text = (title + "\n" + "\n".join(fallback_lines))[:3000]

        if use_plan_blocks:
            ts = self._post_or_update_blocks(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
                blocks=tool_plan_blocks(calls, title=title, show_details=True),
                message_ts=message_ts,
            )
            if ts is not None:
                return ts, True
            logger.warning("plan/task_card blocks rejected; using section fallback")

        body = "\n".join(fallback_lines) or "_Waiting for tools…_"
        fallback_blocks = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":globe_with_meridians: *{title}*",
                    }
                ],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}},
        ]
        ts = self._post_or_update_blocks(
            channel=channel,
            thread_ts=thread_ts,
            text=text,
            blocks=fallback_blocks,
            message_ts=message_ts,
        )
        return ts, False

    @staticmethod
    def _fallback_tool_lines(calls: list[ActiveToolCall]) -> list[str]:
        lines: list[str] = []
        for call in calls:
            prefix = (
                "→"
                if call.status == "in_progress"
                else "✗"
                if call.status == "error"
                else "✓"
            )
            line = f"{prefix} *{call.display_title()}*"
            if details := call.details_text():
                line += f" · {details}"
            if output := call.output_text():
                line += f" → {output}"
            lines.append(line)
        return lines

    def _post_or_update_blocks(
        self,
        *,
        channel: str,
        thread_ts: str,
        text: str,
        blocks: list[dict[str, Any]],
        message_ts: str | None,
    ) -> str | None:
        try:
            if message_ts:
                self.update_message(
                    channel=channel,
                    ts=message_ts,
                    text=text,
                    blocks=blocks,
                )
                return message_ts
            response = self.post_message(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
                blocks=blocks,
            )
            return str(response["ts"]) if response.get("ts") else None
        except Exception:
            logger.exception("Failed to post/update tool activity")
            return None
