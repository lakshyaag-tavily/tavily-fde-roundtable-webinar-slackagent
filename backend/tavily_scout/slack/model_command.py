"""In-memory ``/agent-model`` selector."""

from __future__ import annotations

from typing import Any

from tavily_scout.config import Settings
from tavily_scout.model_selection import preferred_model, set_preferred_model
from tavily_scout.models import MODELS, SLASH_COMMAND, model_label


def apply_slash_command(*, user_id: str, text: str | None) -> str:
    choice = " ".join((text or "").split()).lower()
    if choice in {"list", "ls", "models", "help", "?"}:
        current = preferred_model(user_id)
        lines = ["*Available models*"]
        for alias, option in MODELS.items():
            suffix = "  _(your default)_" if option.id == current else ""
            lines.append(f"• *{option.label}* — `{SLASH_COMMAND} {alias}`{suffix}")
        lines.append(
            "New threads use your default. Selections reset when the process restarts."
        )
        return "\n".join(lines)
    if choice in MODELS:
        model_id = set_preferred_model(user_id, choice)
        return (
            f"Your default is *{model_label(model_id)}*. New threads will use it. "
            "Existing threads stay on their current model."
        )
    if choice in {"", "status", "show", "current"}:
        model_id = preferred_model(user_id)
        return (
            f"Your default is *{model_label(model_id)}*. "
            f"Use `{SLASH_COMMAND} list` to see options."
        )
    aliases = " | ".join(MODELS)
    return f"Unknown model `{choice}`. Use `{SLASH_COMMAND} {aliases} | list | status`."


def slash_result_from_command(command: dict[str, Any], *, settings: Settings) -> str:
    del settings
    return apply_slash_command(
        user_id=str(command.get("user_id") or ""),
        text=str(command.get("text") or ""),
    )
