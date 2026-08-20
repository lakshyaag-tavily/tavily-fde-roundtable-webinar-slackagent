from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env", override=False)


class Settings(BaseSettings):
    """Runtime settings loaded from ``ROUNDTABLE_AGENT_*`` variables."""

    model_config = SettingsConfigDict(
        env_prefix="ROUNDTABLE_AGENT_",
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Tavily Scout"
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None
    slack_bot_user_id: str | None = None
    slack_bot_id: str | None = None
    tavily_api_key: str | None = None

    run_timeout_seconds: int = 600
    recursion_limit: int = 100
    max_model_calls: int = 30
    max_tool_calls: int = 30
    slack_stream_tools: bool = True

    @field_validator(
        "run_timeout_seconds",
        "recursion_limit",
        "max_model_calls",
        "max_tool_calls",
    )
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
