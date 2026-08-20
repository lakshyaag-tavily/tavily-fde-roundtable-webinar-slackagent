"""Slack App Home and Agent View content."""

from __future__ import annotations

from typing import Any

from tavily_scout.model_selection import preferred_model
from tavily_scout.models import MODELS, SLASH_COMMAND, model_label

SELECT_MODEL_ACTION_ID = "select_model"

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


def _model_option_block(alias: str) -> dict[str, Any]:
    option = MODELS[alias]
    return {
        "text": {"type": "plain_text", "text": option.label, "emoji": True},
        "value": alias,
        "description": {
            "type": "plain_text",
            "text": option.id.removeprefix("nebius/").removeprefix("openai/"),
        },
    }


def build_home_view(*, user_id: str) -> dict[str, Any]:
    mention = f"<@{user_id}>" if user_id else "there"
    current = preferred_model(user_id)
    options = [_model_option_block(alias) for alias in MODELS]
    initial = next(
        (option for option in options if MODELS[option["value"]].id == current),
        options[0],
    )
    prompt_lines = "\n".join(
        f"• *{prompt['title']}* — _{prompt['message']}_" for prompt in SUGGESTED_PROMPTS
    )
    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Tavily Scout",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Hey {mention} — ask a question in *Messages* or mention "
                        "me in a channel thread. I search and read the web with Tavily."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Default model*\nCurrently *{model_label(current)}*. "
                        "New threads use this; existing threads stay on the model "
                        "they started with."
                    ),
                },
            },
            {
                "type": "actions",
                "block_id": "model_select",
                "elements": [
                    {
                        "type": "radio_buttons",
                        "action_id": SELECT_MODEL_ACTION_ID,
                        "options": options,
                        "initial_option": initial,
                    }
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"You can also use `{SLASH_COMMAND} list` or "
                            f"`{SLASH_COMMAND} <alias>`."
                        ),
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Try asking*\n{prompt_lines}",
                },
            },
        ],
    }
