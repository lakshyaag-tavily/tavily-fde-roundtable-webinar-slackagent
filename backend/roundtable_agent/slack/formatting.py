"""Convert common Markdown output into Slack mrkdwn."""

from __future__ import annotations

import re


def markdown_to_slack(text: str) -> str:
    result = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", result)
    result = re.sub(r"^[-*_]{3,}$", "", result, flags=re.MULTILINE)
    return result.strip()
