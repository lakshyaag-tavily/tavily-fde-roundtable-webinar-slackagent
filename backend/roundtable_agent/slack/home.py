"""Slack App Home and Agent View content."""

from __future__ import annotations

from typing import Any

SUGGESTED_PROMPTS: list[dict[str, str]] = [
    {
        "title": "Research a current topic",
        "message": "What are the most important recent developments in AI agents?",
    },
    {
        "title": "Compare options",
        "message": "Compare the latest approaches to evaluating web research agents.",
    },
    {
        "title": "Summarize a source",
        "message": "Find and summarize the latest official LangGraph release notes.",
    },
]
SUGGESTED_PROMPTS_TITLE = "What would you like to research?"


def build_home_view(*, user_id: str) -> dict[str, Any]:
    mention = f"<@{user_id}>" if user_id else "there"
    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Roundtable Research Agent",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Hey {mention} — ask a question here or mention me in a "
                        "channel thread. I can search and read the web with Tavily."
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Use `/agent-model list` to see available models and "
                        "`/agent-model <alias>` to choose the default for new threads."
                    ),
                },
            },
        ],
    }
