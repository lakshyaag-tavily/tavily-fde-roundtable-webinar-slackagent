"""The two model choices exposed by the webinar demo."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str


MODELS = {
    "gpt": ModelOption("openai/gpt-5.6-sol", "GPT-5.6 Sol"),
    "opus": ModelOption("anthropic/claude-opus-5", "Claude Opus 5"),
}
DEFAULT_MODEL = MODELS["gpt"].id
SLASH_COMMAND = "/agent-model"


def resolve_model(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("langsmith:"):
        text = text.removeprefix("langsmith:")
    if ":" in text and "/" not in text.split(":", 1)[0]:
        provider, _, name = text.partition(":")
        text = f"{provider}/{name}"
    option = MODELS.get(text.lower())
    if option:
        return option.id
    return text if any(option.id == text for option in MODELS.values()) else None


def model_label(model_id: str) -> str:
    return next(
        (option.label for option in MODELS.values() if option.id == model_id),
        model_id,
    )
