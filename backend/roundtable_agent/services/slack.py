"""Small deterministic wrapper around the Slack Web API."""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from roundtable_agent.config import Settings, get_settings
from roundtable_agent.slack.formatting import markdown_to_slack

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

    def post_or_update_tool_activity(
        self,
        *,
        channel: str,
        thread_ts: str,
        lines: list[str],
        message_ts: str | None,
        done: bool = False,
    ) -> str | None:
        title = "Web research (done)" if done else "Web research"
        body = "\n".join(lines) or "_Waiting for tools…_"
        text = f"{title}\n{body}"[:3000]
        blocks = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":globe_with_meridians: *{title}*"}
                ],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}},
        ]
        try:
            if message_ts:
                self.client.chat_update(
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
            return str(response.get("ts")) if response.get("ts") else None
        except SlackApiError as exc:
            logger.warning("tool activity update failed: %s", exc.response.get("error"))
            return message_ts
