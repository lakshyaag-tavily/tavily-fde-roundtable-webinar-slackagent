from __future__ import annotations

import re
from typing import Any

# Slack user mention: <@U123> or <@U123|display>
_BOT_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|[^>]*)?>")

_CHANNEL_TYPES = frozenset({"channel", "group"})


def strip_bot_mention(text: str, *, bot_user_id: str | None) -> str:
    """Remove the bot's <@U…> mention (and extra whitespace) from event text."""
    if bot_user_id:
        cleaned = re.sub(
            rf"<@{re.escape(bot_user_id)}(?:\|[^>]*)?>",
            "",
            text,
        )
    else:
        # app_mention always leads with the bot; only strip the first mention.
        cleaned = _BOT_MENTION_RE.sub("", text, count=1)
    return " ".join(cleaned.split()).strip()


def is_channel_or_group_message(event: dict[str, Any]) -> bool:
    return event.get("channel_type") in _CHANNEL_TYPES


def should_ignore_message_event(
    event: dict[str, Any], *, bot_user_id: str | None
) -> bool:
    """Return True if this Events API message should not trigger research.

    Filters bot loops, subtypes (edits/joins), and non-IM channels.
    Channel/group traffic is mention-only via ``app_mention`` (caller returns early).
    """
    if event.get("bot_id"):
        return True
    if event.get("subtype"):
        return True
    if bot_user_id and event.get("user") == bot_user_id:
        return True
    # message.im subscription should already scope, but be defensive.
    channel_type = event.get("channel_type")
    if channel_type and channel_type != "im":
        return True
    text = (event.get("text") or "").strip()
    return not text


def should_ignore_app_mention_event(
    event: dict[str, Any], *, bot_user_id: str | None
) -> bool:
    """Return True if this app_mention should not trigger research."""
    if event.get("bot_id"):
        return True
    if event.get("subtype"):
        return True
    if bot_user_id and event.get("user") == bot_user_id:
        return True
    text = strip_bot_mention(event.get("text") or "", bot_user_id=bot_user_id)
    return not text


def research_text_from_event(
    event: dict[str, Any], *, event_type: str, bot_user_id: str | None
) -> str:
    """User-facing request text: strip bot mention for channel @mentions."""
    raw = str(event.get("text") or "")
    if event_type == "app_mention":
        return strip_bot_mention(raw, bot_user_id=bot_user_id)
    return raw.strip()


def event_thread_ts(event: dict[str, Any]) -> str:
    """Reply in-thread: use existing thread_ts or the message ts as root."""
    return str(event.get("thread_ts") or event.get("ts") or "")
